"""Tests for Student Financials, Fee Billing & Payments (Ghana Cedis GH₵)."""
from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.financials.models import SemesterFeeStructure, StudentAccountStatement, Payment, FinancialHold
from apps.financials.services import BillingService
from apps.financials.receipt import PaymentReceiptGenerator

User = get_user_model()


@pytest.fixture
def student_user(db):
    return User.objects.create_user(
        email="kofi.mensah@ug.edu.gh",
        password="TestPassword123!",
        first_name="Kofi",
        last_name="Mensah",
        role="student",
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        email="bursar@ug.edu.gh",
        password="TestPassword123!",
        first_name="Bursar",
        last_name="Officer",
        role="admin",
    )


@pytest.fixture
def fee_structure(db):
    return SemesterFeeStructure.objects.create(
        semester="First Semester 2024/2025",
        academic_fee=Decimal("3850.00"),
        ict_library_fee=Decimal("350.00"),
        src_dues=Decimal("180.00"),
        examination_fee=Decimal("220.00"),
        is_active=True,
    )


@pytest.mark.django_db
class TestFinancialsBilling:
    def test_fee_structure_total(self, fee_structure):
        assert fee_structure.total_semester_fee == Decimal("4600.00")

    def test_statement_initialization_and_hold(self, student_user, fee_structure):
        statement = BillingService.get_or_create_statement(student_user)
        assert statement.total_billed == Decimal("4600.00")
        assert statement.total_paid == Decimal("0.00")
        assert statement.balance == Decimal("4600.00")
        assert statement.status == StudentAccountStatement.Status.UNPAID

        # Verify hold is active because balance > 500
        hold = FinancialHold.objects.filter(student=student_user, is_active=True).first()
        assert hold is not None
        assert hold.amount_due == Decimal("4600.00")

    def test_momo_payment_reduces_balance(self, student_user, fee_structure):
        payment = BillingService.process_momo_payment(
            student=student_user,
            amount=Decimal("2000.00"),
            provider="MTN Mobile Money",
            phone="0244123456",
            reference="MTN-TEST-9988",
        )
        assert payment.status == Payment.Status.COMPLETED
        assert payment.receipt_number.startswith("RCP-GHS-")

        statement = payment.statement
        assert statement.total_paid == Decimal("2000.00")
        assert statement.balance == Decimal("2600.00")
        assert statement.status == StudentAccountStatement.Status.PARTIAL

    def test_full_payment_clears_hold(self, student_user, fee_structure):
        BillingService.get_or_create_statement(student_user)
        assert FinancialHold.objects.filter(student=student_user, is_active=True).exists()

        # Pay in full
        payment = BillingService.process_momo_payment(
            student=student_user,
            amount=Decimal("4600.00"),
            provider="Telecel Cash",
            phone="0209876543",
        )
        statement = payment.statement
        assert statement.balance == Decimal("0.00")
        assert statement.status == StudentAccountStatement.Status.PAID

        # Hold should now be cleared
        assert not FinancialHold.objects.filter(student=student_user, is_active=True).exists()

    def test_bank_api_payment_integration(self, student_user, fee_structure):
        payment = BillingService.process_bank_api_payment(
            student_lookup=student_user.email,
            amount=Decimal("4600.00"),
            bank_name="GCB Bank Ltd",
            teller_ref="GCB-TELLER-2025-01",
            branch="Legon Branch",
            depositor_name="Kwame Mensah",
        )
        assert payment.channel == Payment.Channel.BANK_API
        assert payment.status == Payment.Status.COMPLETED
        assert payment.statement.balance == Decimal("0.00")

    def test_manual_bank_slip_verification(self, student_user, admin_user, fee_structure):
        payment = BillingService.submit_manual_bank_slip(
            student=student_user,
            amount=Decimal("4600.00"),
            bank_name="Ecobank Ghana",
            slip_ref="ECO-SLIP-7766",
        )
        assert payment.status == Payment.Status.PENDING_VERIFICATION
        statement = payment.statement
        # Balance shouldn't deduct yet
        assert statement.balance == Decimal("4600.00")

        # Admin approves
        BillingService.verify_manual_bank_slip(payment, verified_by=admin_user, approve=True)
        payment.refresh_from_db()
        assert payment.status == Payment.Status.COMPLETED
        statement.refresh_from_db()
        assert statement.balance == Decimal("0.00")

    def test_pdf_receipt_generation(self, student_user, fee_structure):
        payment = BillingService.process_momo_payment(
            student=student_user,
            amount=Decimal("2500.00"),
            provider="MTN Mobile Money",
            phone="0244123456",
        )
        pdf_bytes = PaymentReceiptGenerator(payment).generate()
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.django_db
class TestFinancialsAPI:
    def test_my_statement_endpoint(self, student_user, fee_structure):
        client = APIClient()
        client.force_authenticate(user=student_user)

        res = client.get("/api/v1/financials/my-statement/")
        assert res.status_code == 200
        assert res.data["total_billed"] == "4600.00"
        assert res.data["currency"] == "GHS"
        assert res.data["has_active_hold"] is True

    def test_momo_pay_endpoint(self, student_user, fee_structure):
        client = APIClient()
        client.force_authenticate(user=student_user)

        payload = {
            "amount": "1500.00",
            "provider": "MTN Mobile Money",
            "phone": "0551234567",
        }
        res = client.post("/api/v1/financials/pay/momo/", payload)
        assert res.status_code == 201
        assert "payment" in res.data
        assert res.data["payment"]["receipt_number"].startswith("RCP-GHS-")
        assert res.data["statement"]["balance"] == "3100.00"

    def test_bank_lookup_and_notify_webhook(self, student_user, fee_structure):
        client = APIClient()

        # 1. Bank teller queries student
        lookup_res = client.get(f"/api/v1/financials/bank/lookup/?student_id={student_user.email}")
        assert lookup_res.status_code == 200
        assert lookup_res.data["student_name"] == "Kofi Mensah"
        assert Decimal(str(lookup_res.data["balance_due"])) == Decimal("4600.00")

        # 2. Bank teller posts payment
        post_payload = {
            "student_id": student_user.email,
            "amount": "4600.00",
            "bank_name": "Zenith Bank Ghana",
            "teller_ref": "ZEN-ACC-99881",
            "branch": "Accra Central",
            "depositor_name": "Self",
        }
        notify_res = client.post("/api/v1/financials/bank/notify/", post_payload)
        assert notify_res.status_code == 200
        assert notify_res.data["status"] == "SUCCESS"
        assert Decimal(str(notify_res.data["current_balance"])) == Decimal("0.00")

        # 3. Test bank_reference payload alias without teller_ref
        alias_payload = {
            "student_id": student_user.email,
            "amount": "100.00",
            "bank_name": "GCB Bank",
            "bank_reference": "GCB-ALIAS-12345",
        }
        alias_res = client.post("/api/v1/financials/bank/notify/", alias_payload)
        assert alias_res.status_code == 200
        assert alias_res.data["status"] == "SUCCESS"

    def test_receipt_pdf_download_endpoint(self, student_user, fee_structure):
        client = APIClient()
        client.force_authenticate(user=student_user)

        payment = BillingService.process_momo_payment(
            student=student_user,
            amount=Decimal("1000.00"),
            provider="AT Money",
            phone="0271122334",
        )
        res = client.get(f"/api/v1/financials/payments/{payment.id}/receipt/")
        assert res.status_code == 200
        assert res["Content-Type"] == "application/pdf"
        assert res.content.startswith(b"%PDF")

    def test_finance_officer_role_and_multi_level_fees(self, db):
        from apps.users.models import UserProfile

        # Create Finance Officer
        fin_user = User.objects.create_user(
            email="finance.lead@ug.edu.gh",
            password="TestPassword123!",
            first_name="Finance",
            last_name="Director",
            role=User.Role.FINANCE,
        )
        assert fin_user.is_finance_role is True

        # Create Level 400 Student
        senior_student = User.objects.create_user(
            email="senior.student@ug.edu.gh",
            password="TestPassword123!",
            first_name="Ama",
            last_name="Osei",
            role=User.Role.STUDENT,
        )
        UserProfile.objects.create(user=senior_student, academic_level="400")
        assert senior_student.academic_level == "400"

        # Initialize statement for senior student
        stmt = BillingService.get_or_create_statement(senior_student)
        assert stmt.academic_level == "400"
        # Default Level 400 has GH₵ 5,000 total
        assert stmt.total_billed == Decimal("5000.00")

        # Finance officer updates Level 400 fee structure dynamically
        client = APIClient()
        client.force_authenticate(user=fin_user)

        update_payload = {
            "semester": "First Semester 2024/2025",
            "academic_level": "400",
            "level_title": "Level 400 (Seniors & Finalists)",
            "academic_fee": "4300.00",
            "ict_library_fee": "400.00",
            "src_dues": "200.00",
            "examination_fee": "400.00",
            "recalculate_students": True,
        }
        res = client.post("/api/v1/financials/admin/fee-structure/", update_payload)
        assert res.status_code == 200
        assert Decimal(str(res.data["fee_structure"]["total_fee"])) == Decimal("5300.00")

        # Verify senior student statement updated dynamically
        stmt.refresh_from_db()
        assert stmt.total_billed == Decimal("5300.00")
        assert stmt.balance == Decimal("5300.00")

    def test_staff_cannot_access_financials(self, admin_user, fee_structure):
        staff_user = User.objects.create_user(
            email="academic.officer@ug.edu.gh",
            password="TestPassword123!",
            role="staff",
            first_name="Academic",
            last_name="Registrar",
        )
        fin_user = User.objects.create_user(
            email="bursar.clerk@ug.edu.gh",
            password="TestPassword123!",
            role="finance",
            first_name="Bursar",
            last_name="Clerk",
        )

        client = APIClient()

        # 1. Staff officer should receive 403 Forbidden
        client.force_authenticate(user=staff_user)
        res_staff = client.get("/api/v1/financials/admin/overview/")
        assert res_staff.status_code == 403

        # 2. Finance officer should receive 200 OK
        client.force_authenticate(user=fin_user)
        res_fin = client.get("/api/v1/financials/admin/overview/")
        assert res_fin.status_code == 200

        # 3. Super Admin should receive 200 OK
        client.force_authenticate(user=admin_user)
        res_admin = client.get("/api/v1/financials/admin/overview/")
        assert res_admin.status_code == 200
