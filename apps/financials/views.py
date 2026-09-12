"""API Views for Student Financials & Billing (Ghana Cedis GH₵)."""
from decimal import Decimal
from django.db.models import Sum, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import SemesterFeeStructure, StudentAccountStatement, Payment, FinancialHold
from .services import BillingService
from .receipt import PaymentReceiptGenerator
from .serializers import (
    StudentAccountStatementSerializer,
    PaymentSerializer,
    SemesterFeeStructureSerializer,
    MoMoPaymentRequestSerializer,
    ManualBankSlipRequestSerializer,
    BankNotificationRequestSerializer,
    BankStudentLookupSerializer,
)

User = get_user_model()


class StudentStatementView(APIView):
    """GET /api/v1/financials/my-statement/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        statement = BillingService.get_or_create_statement(request.user)
        serializer = StudentAccountStatementSerializer(statement)
        return Response(serializer.data)


class MoMoPaymentView(APIView):
    """POST /api/v1/financials/pay/momo/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = MoMoPaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = BillingService.process_momo_payment(
                student=request.user,
                amount=data["amount"],
                provider=data["provider"],
                phone=data["phone"],
                reference=data.get("reference"),
            )
            statement = payment.statement
            return Response({
                "message": f"Payment of GH₵ {payment.amount:,.2f} via {payment.provider} completed successfully.",
                "payment": PaymentSerializer(payment).data,
                "statement": StudentAccountStatementSerializer(statement).data,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SubmitBankSlipView(APIView):
    """POST /api/v1/financials/pay/bank-slip/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ManualBankSlipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        slip_image = request.FILES.get("slip_image")

        try:
            payment = BillingService.submit_manual_bank_slip(
                student=request.user,
                amount=data["amount"],
                bank_name=data["bank_name"],
                slip_ref=data["slip_ref"],
                slip_image=slip_image,
                notes=data.get("notes", ""),
            )
            return Response({
                "message": "Bank deposit slip submitted successfully. It will be credited once verified by the Accounts Office.",
                "payment": PaymentSerializer(payment).data,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PaymentReceiptPDFView(APIView):
    """GET /api/v1/financials/payments/<id>/receipt/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        # Check permissions: owner or staff/admin
        if payment.student != request.user and not (request.user.is_staff or getattr(request.user, "role", "") in ("staff", "admin")):
            return Response({"detail": "Permission denied to view this receipt."}, status=status.HTTP_403_FORBIDDEN)

        pdf_bytes = PaymentReceiptGenerator(payment).generate()
        filename = f"Payment_Receipt_{payment.receipt_number}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


class BankStudentLookupView(APIView):
    """GET /api/v1/financials/bank/lookup/?student_id=..."""
    # Open for bank teller system or admin simulation
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        student_id_str = request.query_params.get("student_id", "").strip()
        if not student_id_str:
            return Response({"detail": "student_id parameter is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Lookup student by ID, email, student_id, or UUID
        student = BillingService.find_student_by_identifier(student_id_str)
        if not student:
            return Response({"detail": f"No student found with ID or Index Number: {student_id_str}"}, status=status.HTTP_404_NOT_FOUND)

        statement = BillingService.get_or_create_statement(student)
        student_name = f"{student.first_name} {student.last_name}".strip() or student.email
        index_num = getattr(student, "student_id", None) or f"UG-{str(student.id)[:8].upper()}"
        program_name = getattr(student, "department", "General Studies") or "Undergraduate Degree"

        data = {
            "student_id": index_num,
            "student_name": student_name,
            "program": program_name,
            "semester": statement.semester,
            "total_billed": statement.total_billed,
            "total_paid": statement.total_paid,
            "balance_due": statement.balance,
            "status": statement.get_status_display(),
        }
        return Response(BankStudentLookupSerializer(data).data)


class BankPaymentNotificationView(APIView):
    """POST /api/v1/financials/bank/notify/"""
    # Automated Bank Collect Webhook
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = BankNotificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = BillingService.process_bank_api_payment(
                student_lookup=data["student_id"],
                amount=data["amount"],
                bank_name=data["bank_name"],
                teller_ref=data["teller_ref"],
                branch=data.get("branch", ""),
                depositor_name=data.get("depositor_name", ""),
            )
            return Response({
                "status": "SUCCESS",
                "message": f"Payment of GH₵ {payment.amount:,.2f} recorded and credited successfully.",
                "receipt_number": payment.receipt_number,
                "current_balance": payment.statement.balance,
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"status": "FAILED", "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class IsFinanceOrAdmin(permissions.BasePermission):
    """Allow superusers, admins, or users with the 'finance' role."""
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and (
                request.user.is_superuser or
                getattr(request.user, "role", "") in ("finance", "admin")
            )
        )


class AdminFinancialsOverviewView(APIView):
    """GET /api/v1/financials/admin/overview/"""
    permission_classes = [IsFinanceOrAdmin]

    def get(self, request):
        statements = StudentAccountStatement.objects.all()
        total_billed = statements.aggregate(total=Sum("total_billed"))["total"] or Decimal("0.00")
        total_paid = statements.aggregate(total=Sum("total_paid"))["total"] or Decimal("0.00")
        total_arrears = statements.aggregate(total=Sum("balance"))["total"] or Decimal("0.00")

        # Breakdown by channel
        momo_total = Payment.objects.filter(channel=Payment.Channel.MOMO, status=Payment.Status.COMPLETED).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
        bank_total = Payment.objects.filter(channel__in=[Payment.Channel.BANK_API, Payment.Channel.BANK_MANUAL], status=Payment.Status.COMPLETED).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")

        recent_payments = Payment.objects.all().select_related("student", "statement")[:25]
        pending_slips = Payment.objects.filter(status=Payment.Status.PENDING_VERIFICATION).select_related("student", "statement")
        active_holds_count = FinancialHold.objects.filter(is_active=True).count()

        BillingService.ensure_default_level_structures()
        all_structures = SemesterFeeStructure.objects.filter(is_active=True).order_by("academic_level")
        active_struct = all_structures.first() or BillingService.get_active_fee_structure()

        # Calculate collection rate
        collection_rate = (
            round((float(total_paid) / float(total_billed) * 100), 1)
            if total_billed > 0
            else 0.0
        )

        level_breakdown = []
        for level_code, level_label in [
            ("100", "Level 100 (Freshmen)"),
            ("200", "Level 200 (Sophomores)"),
            ("300", "Level 300 (Juniors)"),
            ("400", "Level 400 (Seniors)"),
            ("postgraduate", "Postgraduate"),
        ]:
            lvl_stmts = statements.filter(academic_level=level_code)
            lvl_billed = lvl_stmts.aggregate(t=Sum("total_billed"))["t"] or Decimal("0.00")
            lvl_paid = lvl_stmts.aggregate(t=Sum("total_paid"))["t"] or Decimal("0.00")
            lvl_arrears = lvl_stmts.aggregate(t=Sum("balance"))["t"] or Decimal("0.00")
            lvl_holds = FinancialHold.objects.filter(student__profile__academic_level=level_code, is_active=True).count()
            lvl_rate = round((float(lvl_paid) / float(lvl_billed) * 100), 1) if lvl_billed > 0 else 0.0
            level_breakdown.append({
                "level": level_code,
                "title": level_label,
                "student_count": lvl_stmts.count(),
                "total_billed": lvl_billed,
                "total_paid": lvl_paid,
                "total_arrears": lvl_arrears,
                "active_holds": lvl_holds,
                "collection_rate": lvl_rate,
            })

        return Response({
            "metrics": {
                "total_billed": total_billed,
                "total_paid": total_paid,
                "total_arrears": total_arrears,
                "collection_rate": collection_rate,
                "momo_total": momo_total,
                "bank_total": bank_total,
                "active_holds_count": active_holds_count,
                "level_breakdown": level_breakdown,
            },
            "active_fee_structure": SemesterFeeStructureSerializer(active_struct).data,
            "fee_structures": SemesterFeeStructureSerializer(all_structures, many=True).data,
            "recent_payments": PaymentSerializer(recent_payments, many=True).data,
            "pending_bank_slips": PaymentSerializer(pending_slips, many=True).data,
        })


class AdminVerifySlipView(APIView):
    """POST /api/v1/financials/admin/verify-slip/<id>/"""
    permission_classes = [IsFinanceOrAdmin]

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        approve = request.data.get("approve", True)
        payment = BillingService.verify_manual_bank_slip(payment, verified_by=request.user, approve=approve)

        action_word = "approved and credited" if approve else "rejected"
        return Response({
            "message": f"Bank deposit slip {payment.reference_number} has been {action_word}.",
            "payment": PaymentSerializer(payment).data,
        })


class AdminAdjustStatementView(APIView):
    """POST /api/v1/financials/admin/adjust/"""
    permission_classes = [IsFinanceOrAdmin]

    def post(self, request):
        student_id = request.data.get("student_id")
        bursary_amount = Decimal(str(request.data.get("bursary_amount", "0.00")))
        note = request.data.get("note", "")

        student = get_object_or_404(User, pk=student_id)
        statement = BillingService.get_or_create_statement(student)
        BillingService.apply_bursary_award(statement, bursary_amount, note)

        return Response({
            "message": f"Applied GH₵ {bursary_amount:,.2f} bursary to {student.email}.",
            "statement": StudentAccountStatementSerializer(statement).data,
        })


class AdminFeeStructureView(APIView):
    """GET, POST /api/v1/financials/admin/fee-structure/"""
    permission_classes = [IsFinanceOrAdmin]

    def get(self, request):
        level = request.query_params.get("level")
        semester = request.query_params.get("semester")

        BillingService.ensure_default_level_structures(semester or "First Semester 2024/2025")
        structures = SemesterFeeStructure.objects.filter(is_active=True)
        if semester:
            structures = structures.filter(semester=semester)
        if level:
            structures = structures.filter(academic_level=level)

        structures = structures.order_by("academic_level")
        return Response(SemesterFeeStructureSerializer(structures, many=True).data)

    def post(self, request):
        semester = request.data.get("semester", "First Semester 2024/2025")
        academic_level = str(request.data.get("academic_level", "100"))
        level_title = request.data.get("level_title")
        recalculate = bool(request.data.get("recalculate_students", True))

        academic_fee = Decimal(str(request.data.get("academic_fee", "3850.00")))
        ict_fee = Decimal(str(request.data.get("ict_library_fee", "350.00")))
        src_dues = Decimal(str(request.data.get("src_dues", "180.00")))
        exam_fee = Decimal(str(request.data.get("examination_fee", "220.00")))

        struct = BillingService.update_or_create_level_fee_structure(
            semester=semester,
            academic_level=academic_level,
            academic_fee=academic_fee,
            ict_library_fee=ict_fee,
            src_dues=src_dues,
            examination_fee=exam_fee,
            level_title=level_title,
            propagate_to_students=recalculate,
        )

        all_structures = SemesterFeeStructure.objects.filter(semester=semester, is_active=True).order_by("academic_level")

        return Response({
            "message": f"Fee structure for {struct.get_academic_level_display()} updated successfully in Ghana Cedis (GH₵).",
            "fee_structure": SemesterFeeStructureSerializer(struct).data,
            "all_structures": SemesterFeeStructureSerializer(all_structures, many=True).data,
        })


class AdminExportStatementsView(APIView):
    """GET /api/v1/financials/admin/export/statements/ — export student fee statements in CSV."""
    permission_classes = [IsFinanceOrAdmin]

    def get(self, request):
        from .exports import export_student_statements_csv
        semester = request.query_params.get("semester")
        level = request.query_params.get("level")
        status_filter = request.query_params.get("status")
        return export_student_statements_csv(semester=semester, academic_level=level, status_filter=status_filter)


class AdminExportPaymentsView(APIView):
    """GET /api/v1/financials/admin/export/payments/ — export payments transaction ledger in CSV."""
    permission_classes = [IsFinanceOrAdmin]

    def get(self, request):
        from .exports import export_payments_ledger_csv
        channel = request.query_params.get("channel")
        status_filter = request.query_params.get("status")
        return export_payments_ledger_csv(channel=channel, status_filter=status_filter)


class StudentExportStatementView(APIView):
    """GET /api/v1/financials/statement/export-csv/ — student exports personal statement ledger."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .exports import export_student_personal_statement_csv
        return export_student_personal_statement_csv(request.user)
