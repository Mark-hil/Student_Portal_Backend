"""Business logic for student billing, payments, and financial holds."""
from decimal import Decimal
import logging
import uuid
from django.db import transaction, models
from django.db.models import Q, Sum
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import SemesterFeeStructure, StudentAccountStatement, Payment, FinancialHold, RefundRequest

logger = logging.getLogger(__name__)
User = get_user_model()


class BillingService:
    @classmethod
    def ensure_default_level_structures(cls, semester: str = "First Semester 2024/2025"):
        """Ensure standard Ghanaian higher-ed fee schedules exist for all academic levels."""
        defaults = [
            {
                "academic_level": "100",
                "level_title": "Level 100 (Freshmen)",
                "academic_fee": Decimal("4200.00"),
                "ict_library_fee": Decimal("450.00"),
                "src_dues": Decimal("250.00"),
                "examination_fee": Decimal("300.00"),
            },
            {
                "academic_level": "200",
                "level_title": "Level 200 (Sophomores)",
                "academic_fee": Decimal("3850.00"),
                "ict_library_fee": Decimal("350.00"),
                "src_dues": Decimal("180.00"),
                "examination_fee": Decimal("220.00"),
            },
            {
                "academic_level": "300",
                "level_title": "Level 300 (Juniors)",
                "academic_fee": Decimal("3850.00"),
                "ict_library_fee": Decimal("350.00"),
                "src_dues": Decimal("180.00"),
                "examination_fee": Decimal("220.00"),
            },
            {
                "academic_level": "400",
                "level_title": "Level 400 (Seniors / Final Year)",
                "academic_fee": Decimal("4100.00"),
                "ict_library_fee": Decimal("350.00"),
                "src_dues": Decimal("200.00"),
                "examination_fee": Decimal("350.00"),
            },
            {
                "academic_level": "postgraduate",
                "level_title": "Postgraduate / Masters",
                "academic_fee": Decimal("5800.00"),
                "ict_library_fee": Decimal("450.00"),
                "src_dues": Decimal("250.00"),
                "examination_fee": Decimal("300.00"),
            },
        ]
        due_date = timezone.now().date() + timezone.timedelta(days=60)
        for d in defaults:
            SemesterFeeStructure.objects.get_or_create(
                semester=semester,
                academic_level=d["academic_level"],
                defaults={
                    "level_title": d["level_title"],
                    "academic_fee": d["academic_fee"],
                    "ict_library_fee": d["ict_library_fee"],
                    "src_dues": d["src_dues"],
                    "examination_fee": d["examination_fee"],
                    "due_date": due_date,
                    "is_active": True,
                }
            )

    @classmethod
    def get_fee_structure_for_level(cls, academic_level: str = "100", semester: str = None) -> SemesterFeeStructure:
        """Fetch the active fee structure configured for a specific academic level."""
        target_semester = semester or "First Semester 2024/2025"
        cls.ensure_default_level_structures(target_semester)

        # 1. Try exact level match
        struct = SemesterFeeStructure.objects.filter(
            semester=target_semester,
            academic_level=str(academic_level),
            is_active=True
        ).first()

        # 2. Fallback to "all" levels structure
        if not struct:
            struct = SemesterFeeStructure.objects.filter(
                semester=target_semester,
                academic_level="all",
                is_active=True
            ).first()

        # 3. Fallback to any active structure
        if not struct:
            struct = SemesterFeeStructure.objects.filter(is_active=True).first()

        return struct

    @classmethod
    def get_active_fee_structure(cls, academic_level: str = "100", semester: str = None) -> SemesterFeeStructure:
        """Fetch active semester fee structure (supports level lookup)."""
        return cls.get_fee_structure_for_level(academic_level=academic_level, semester=semester)

    @classmethod
    def get_or_create_statement(cls, student, semester: str = None) -> StudentAccountStatement:
        """Get or initialize the semester statement for a student based on their dynamic academic level,
        automatically carrying forward any credit overpayments or unpaid arrears from previous semesters."""
        student_level = getattr(student, "academic_level", "100") or "100"
        fee_struct = cls.get_fee_structure_for_level(academic_level=student_level, semester=semester)
        target_semester = semester or fee_struct.semester

        statement, created = StudentAccountStatement.objects.get_or_create(
            student=student,
            semester=target_semester,
            defaults={
                "academic_level": student_level,
                "academic_fee": fee_struct.academic_fee,
                "ict_library_fee": fee_struct.ict_library_fee,
                "src_dues": fee_struct.src_dues,
                "examination_fee": fee_struct.examination_fee,
                "total_billed": fee_struct.total_semester_fee,
                "total_paid": Decimal("0.00"),
                "balance": fee_struct.total_semester_fee,
                "credit_balance": Decimal("0.00"),
                "previous_credit_applied": Decimal("0.00"),
                "previous_arrears_applied": Decimal("0.00"),
                "due_date": fee_struct.due_date,
                "status": StudentAccountStatement.Status.UNPAID,
            }
        )

        if created:
            # Check for previous semester statement to roll over credit surplus or unpaid arrears
            prev_statement = (
                StudentAccountStatement.objects.filter(student=student)
                .exclude(id=statement.id)
                .order_by("-created_at")
                .first()
            )
            if prev_statement:
                # 1. If previous semester had a credit surplus (student overpaid):
                if prev_statement.credit_balance > Decimal("0.00"):
                    statement.previous_credit_applied = prev_statement.credit_balance
                    logger.info(
                        "Carried forward credit overpayment of GH₵ %s from %s for %s",
                        prev_statement.credit_balance, prev_statement.semester, student.email
                    )
                # 2. If previous semester had unpaid debt (arrears):
                elif prev_statement.balance > Decimal("0.00"):
                    statement.previous_arrears_applied = prev_statement.balance
                    logger.info(
                        "Carried forward unpaid arrears of GH₵ %s from %s for %s",
                        prev_statement.balance, prev_statement.semester, student.email
                    )
                statement.save(update_fields=["previous_credit_applied", "previous_arrears_applied"])

        statement.recalculate()
        cls.sync_financial_hold(student, statement)
        return statement

    @classmethod
    def update_or_create_level_fee_structure(
        cls,
        semester: str,
        academic_level: str,
        academic_fee: Decimal,
        ict_library_fee: Decimal,
        src_dues: Decimal,
        examination_fee: Decimal,
        level_title: str = None,
        due_date = None,
        propagate_to_students: bool = True,
    ) -> SemesterFeeStructure:
        """Dynamically update or create fee structure for an academic level and propagate to student statements."""
        struct, _ = SemesterFeeStructure.objects.update_or_create(
            semester=semester,
            academic_level=academic_level,
            defaults={
                "academic_fee": academic_fee,
                "ict_library_fee": ict_library_fee,
                "src_dues": src_dues,
                "examination_fee": examination_fee,
                "level_title": level_title or f"Level {academic_level}",
                "due_date": due_date,
                "is_active": True,
            }
        )

        if propagate_to_students:
            cls.recalculate_level_statements(semester, academic_level, struct)

        return struct

    @classmethod
    def recalculate_level_statements(cls, semester: str, academic_level: str, struct: SemesterFeeStructure = None):
        """Update billing charges on student statements for students belonging to this level."""
        if not struct:
            struct = cls.get_fee_structure_for_level(academic_level=academic_level, semester=semester)

        # Statements for this semester and matching academic_level
        statements = StudentAccountStatement.objects.filter(
            semester=semester,
            academic_level=academic_level
        )

        for stmt in statements:
            stmt.academic_fee = struct.academic_fee
            stmt.ict_library_fee = struct.ict_library_fee
            stmt.src_dues = struct.src_dues
            stmt.examination_fee = struct.examination_fee
            stmt.recalculate()
            cls.sync_financial_hold(stmt.student, stmt)

    @classmethod
    def sync_financial_hold(cls, student, statement: StudentAccountStatement):
        """Place or lift academic registration hold based on arrears threshold (GH₵ 500.00)."""
        active_hold = FinancialHold.objects.filter(student=student, is_active=True).first()

        # If arrears > 500.00 GH₵ and past due date or unpaid
        if statement.balance > Decimal("500.00"):
            if not active_hold:
                FinancialHold.objects.create(
                    student=student,
                    reason=f"Outstanding semester fee balance of GH₵ {statement.balance:,.2f} exceeds threshold.",
                    amount_due=statement.balance,
                    is_active=True,
                )
            else:
                active_hold.amount_due = statement.balance
                active_hold.save(update_fields=["amount_due"])
        else:
            # Arrears <= 500.00 GH₵, automatically clear hold
            if active_hold:
                active_hold.clear()

    @classmethod
    def _generate_receipt_number(cls) -> str:
        """Generate human-friendly official receipt number e.g. RCP-GHS-2025-A8F12"""
        year = timezone.now().year
        token = uuid.uuid4().hex[:6].upper()
        return f"RCP-GHS-{year}-{token}"

    @classmethod
    def process_momo_payment(
        cls,
        student,
        amount: Decimal,
        provider: str,
        phone: str,
        reference: str = None
    ) -> Payment:
        """Process instant Mobile Money payment (MTN MoMo, Telecel Cash, AT Money)."""
        if amount <= Decimal("0.00"):
            raise ValueError("Payment amount must be greater than zero.")

        statement = cls.get_or_create_statement(student)
        ref = reference or f"MOMO-{uuid.uuid4().hex[:8].upper()}"
        receipt_num = cls._generate_receipt_number()

        with transaction.atomic():
            payment = Payment.objects.create(
                statement=statement,
                student=student,
                amount=amount,
                channel=Payment.Channel.MOMO,
                provider=provider,
                phone_or_account=phone,
                reference_number=ref,
                receipt_number=receipt_num,
                status=Payment.Status.COMPLETED,
                notes=f"Mobile Money payment via {provider} ({phone})",
            )
            statement.recalculate()
            cls.sync_financial_hold(student, statement)

        logger.info("MoMo payment %s of GH₵ %s completed for %s", receipt_num, amount, student.email)
        return payment

    @classmethod
    def find_student_by_identifier(cls, identifier: str):
        """Lookup student user by student_id, index number, email, or UUID."""
        if not identifier:
            return None
        clean_str = str(identifier).strip()

        # 1. Exact match by student_id (e.g. STU-2024-8891) or email
        student = User.objects.filter(
            Q(student_id__iexact=clean_str) |
            Q(email__iexact=clean_str)
        ).first()
        if student:
            return student

        # 2. Match by UUID primary key
        try:
            student = User.objects.filter(id=clean_str).first()
            if student:
                return student
        except Exception:
            pass

        # 3. Match by UG- prefix pattern (e.g. UG-EFC197AE)
        if clean_str.upper().startswith("UG-"):
            prefix_part = clean_str[3:].lower()
            student = User.objects.filter(id__istartswith=prefix_part).first()
            if student:
                return student

        # 4. Partial/contains match on student_id or email
        student = User.objects.filter(
            Q(student_id__icontains=clean_str) |
            Q(email__icontains=clean_str)
        ).first()
        if student:
            return student

        return None

    @classmethod
    def process_bank_api_payment(
        cls,
        student_lookup: str,
        amount: Decimal,
        bank_name: str,
        teller_ref: str,
        branch: str = "",
        depositor_name: str = ""
    ) -> Payment:
        """Process automated payment from Partner Bank Collect API (GCB, Ecobank, Zenith, CalBank)."""
        if amount <= Decimal("0.00"):
            raise ValueError("Payment amount must be greater than zero.")

        # Match student by student_id (e.g. STU-2024-8891), email, or UUID
        student = cls.find_student_by_identifier(student_lookup)
        if not student:
            raise ValueError(f"Student not found with identifier: {student_lookup}")

        statement = cls.get_or_create_statement(student)
        receipt_num = cls._generate_receipt_number()

        with transaction.atomic():
            payment = Payment.objects.create(
                statement=statement,
                student=student,
                amount=amount,
                channel=Payment.Channel.BANK_API,
                provider=bank_name,
                phone_or_account=teller_ref,
                reference_number=teller_ref,
                receipt_number=receipt_num,
                status=Payment.Status.COMPLETED,
                notes=f"Bank Branch Deposit at {bank_name} ({branch}). Depositor: {depositor_name}",
            )
            statement.recalculate()
            cls.sync_financial_hold(student, statement)

        logger.info("Bank API payment %s of GH₵ %s completed for %s", receipt_num, amount, student.email)
        return payment

    @classmethod
    def submit_manual_bank_slip(
        cls,
        student,
        amount: Decimal,
        bank_name: str,
        slip_ref: str,
        slip_image=None,
        notes: str = ""
    ) -> Payment:
        """Submit paper bank deposit slip for Bursar verification."""
        if amount <= Decimal("0.00"):
            raise ValueError("Payment amount must be greater than zero.")

        statement = cls.get_or_create_statement(student)
        receipt_num = cls._generate_receipt_number()

        payment = Payment.objects.create(
            statement=statement,
            student=student,
            amount=amount,
            channel=Payment.Channel.BANK_MANUAL,
            provider=bank_name,
            phone_or_account=slip_ref,
            reference_number=slip_ref,
            receipt_number=receipt_num,
            status=Payment.Status.PENDING_VERIFICATION,
            slip_image=slip_image,
            notes=notes or f"Manual Bank Pay-In Slip for {bank_name} Ref: {slip_ref}",
        )
        return payment

    @classmethod
    def verify_manual_bank_slip(cls, payment: Payment, verified_by, approve: bool = True, notes: str = "") -> Payment:
        """Bursar verifies or rejects a manual bank deposit slip."""
        with transaction.atomic():
            if approve:
                payment.status = Payment.Status.COMPLETED
                payment.verified_by = verified_by
                payment.verified_at = timezone.now()
                if notes:
                    payment.notes = notes
                payment.save(update_fields=["status", "verified_by", "verified_at", "notes"])
                payment.statement.recalculate()
                cls.sync_financial_hold(payment.student, payment.statement)
            else:
                payment.status = Payment.Status.FAILED
                payment.verified_by = verified_by
                payment.verified_at = timezone.now()
                payment.notes = f"Declined: {notes}" if notes else "Declined by Accounts Office"
                payment.save(update_fields=["status", "verified_by", "verified_at", "notes"])

        return payment

    @classmethod
    def apply_bursary_award(cls, statement: StudentAccountStatement, bursary_amount: Decimal, note: str = ""):
        """Apply institutional scholarship or bursary waiver to student statement."""
        statement.bursary_aid += bursary_amount
        statement.recalculate()
        cls.sync_financial_hold(statement.student, statement)
        return statement

    @classmethod
    def bill_students_for_semester(cls, semester: str, academic_level: str = None) -> dict:
        """Bulk bill enrolled students for a semester based on the configured fee schedules."""
        students_query = User.objects.filter(role="student", is_active=True, is_deleted=False)
        if academic_level and academic_level != "all":
            students_query = students_query.filter(academic_level=str(academic_level))

        students = list(students_query)
        billed_count = 0
        total_billed_amount = Decimal("0.00")
        total_credits_applied = Decimal("0.00")

        with transaction.atomic():
            for student in students:
                stmt = cls.get_or_create_statement(student, semester=semester)
                billed_count += 1
                total_billed_amount += stmt.total_billed
                total_credits_applied += stmt.previous_credit_applied

        logger.info(
            "Bulk billed %d students for %s. Total billed: GH₵ %s, Rollover credits applied: GH₵ %s",
            billed_count, semester, total_billed_amount, total_credits_applied
        )
        return {
            "semester": semester,
            "academic_level": academic_level or "all",
            "billed_count": billed_count,
            "total_billed": total_billed_amount,
            "total_credits_applied": total_credits_applied,
        }

    @classmethod
    def request_refund(
        cls,
        student,
        amount: Decimal,
        channel: str,
        account_details: str,
        reason: str = "",
        statement: StudentAccountStatement = None
    ) -> RefundRequest:
        """Submit a student refund request against an existing credit surplus (overpayment)."""
        if amount <= Decimal("0.00"):
            raise ValueError("Refund amount must be greater than zero.")

        target_stmt = statement or cls.get_or_create_statement(student)
        target_stmt.recalculate()

        if target_stmt.credit_balance < amount:
            raise ValueError(
                f"Requested refund (GH₵ {amount:,.2f}) exceeds available credit balance "
                f"(GH₵ {target_stmt.credit_balance:,.2f})."
            )

        # Ensure no pending request exceeds available balance
        pending_total = RefundRequest.objects.filter(
            statement=target_stmt,
            status=RefundRequest.Status.PENDING
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

        if (pending_total + amount) > target_stmt.credit_balance:
            raise ValueError(
                f"You already have GH₵ {pending_total:,.2f} in pending refund requests. "
                f"Total requested would exceed your credit balance of GH₵ {target_stmt.credit_balance:,.2f}."
            )

        refund_req = RefundRequest.objects.create(
            student=student,
            statement=target_stmt,
            amount=amount,
            channel=channel,
            account_details=account_details,
            reason=reason or "Fee overpayment refund request",
            status=RefundRequest.Status.PENDING,
        )
        return refund_req

    @classmethod
    def process_refund(
        cls,
        refund_req: RefundRequest,
        reviewed_by,
        approve: bool = True,
        disbursement_ref: str = "",
        admin_notes: str = ""
    ) -> RefundRequest:
        """Bursar / Accounts Office approves and disburses or rejects a student refund request."""
        with transaction.atomic():
            refund_req.reviewed_by = reviewed_by
            refund_req.reviewed_at = timezone.now()
            refund_req.admin_notes = admin_notes

            if approve:
                refund_req.status = RefundRequest.Status.DISBURSED
                refund_req.disbursement_reference = disbursement_ref or f"RFND-{uuid.uuid4().hex[:8].upper()}"
                refund_req.save()

                # Update statement refunded amount and recalculate
                statement = refund_req.statement
                statement.refunded_amount += refund_req.amount
                statement.recalculate()
                cls.sync_financial_hold(statement.student, statement)
                logger.info(
                    "Disbursed refund of GH₵ %s for %s. Ref: %s",
                    refund_req.amount, refund_req.student.email, refund_req.disbursement_reference
                )
            else:
                refund_req.status = RefundRequest.Status.REJECTED
                refund_req.save()

        return refund_req
