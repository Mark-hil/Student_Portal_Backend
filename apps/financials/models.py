"""Models for Student Financials & Fee Billing (Ghana Cedis GHS)."""
from decimal import Decimal
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class SemesterFeeStructure(models.Model):
    """Configured flat semester fee rates for the university by academic level."""
    class AcademicLevel(models.TextChoices):
        LEVEL_100 = "100", "Level 100 (Freshmen)"
        LEVEL_200 = "200", "Level 200 (Sophomores)"
        LEVEL_300 = "300", "Level 300 (Juniors)"
        LEVEL_400 = "400", "Level 400 (Seniors / Final Year)"
        POSTGRADUATE = "postgraduate", "Postgraduate / Masters"
        ALL = "all", "All Levels (Standard Tariff)"

    semester = models.CharField(max_length=60, default="First Semester 2024/2025")
    academic_level = models.CharField(
        max_length=20,
        choices=AcademicLevel.choices,
        default=AcademicLevel.LEVEL_100,
        db_index=True,
    )
    level_title = models.CharField(max_length=100, blank=True, default="Level 100 (Freshmen)")
    academic_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("3850.00"))
    ict_library_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("350.00"))
    src_dues = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("180.00"))
    examination_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("220.00"))
    due_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("semester", "academic_level")
        ordering = ["academic_level", "-created_at"]
        verbose_name = "Semester Fee Structure"
        verbose_name_plural = "Semester Fee Structures"

    @property
    def total_semester_fee(self) -> Decimal:
        return self.academic_fee + self.ict_library_fee + self.src_dues + self.examination_fee

    def __str__(self):
        return f"{self.semester} - {self.get_academic_level_display()} (GH₵ {self.total_semester_fee:,.2f})"


class StudentAccountStatement(models.Model):
    """Semester billing ledger statement for an individual student."""
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIAL = "partial", "Part Payment"
        PAID = "paid", "Paid in Full"
        OVERDUE = "overdue", "Overdue"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="financial_statements"
    )
    semester = models.CharField(max_length=60, default="First Semester 2024/2025")
    academic_level = models.CharField(max_length=20, default="100", blank=True)
    academic_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("3850.00"))
    ict_library_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("350.00"))
    src_dues = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("180.00"))
    examination_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("220.00"))
    bursary_aid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    previous_credit_applied = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), help_text="Overpayment surplus brought forward from previous semester")
    previous_arrears_applied = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), help_text="Unpaid balance brought forward from previous semester")
    total_billed = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("4600.00"))
    total_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), help_text="Total refund amount disbursed to student")
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("4600.00"), help_text="Outstanding arrears owed by student")
    credit_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), help_text="Surplus credit owed to student by the institution")
    currency = models.CharField(max_length=10, default="GHS")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "semester")
        ordering = ["-created_at"]

    def recalculate(self):
        """Update billing totals, balances, and credit surplus based on payments and refunds."""
        raw_billed = (
            self.academic_fee + self.ict_library_fee + self.src_dues + self.examination_fee
            + self.previous_arrears_applied - self.bursary_aid - self.previous_credit_applied
        )
        if raw_billed < Decimal("0.00"):
            self.total_billed = Decimal("0.00")
        else:
            self.total_billed = raw_billed

        # Sum completed payments
        completed_total = self.payments.filter(status=Payment.Status.COMPLETED).aggregate(
            total=models.Sum("amount")
        )["total"] or Decimal("0.00")

        self.total_paid = completed_total

        # Net effective payments after refunds
        net_paid = self.total_paid - self.refunded_amount
        if net_paid < Decimal("0.00"):
            net_paid = Decimal("0.00")

        diff = self.total_billed - net_paid
        if diff > Decimal("0.00"):
            self.balance = diff
            self.credit_balance = Decimal("0.00")
            if self.total_paid > Decimal("0.00"):
                self.status = self.Status.PARTIAL
            elif self.due_date and timezone.now().date() > self.due_date:
                self.status = self.Status.OVERDUE
            else:
                self.status = self.Status.UNPAID
        else:
            self.balance = Decimal("0.00")
            self.credit_balance = abs(diff)
            self.status = self.Status.PAID

        self.save()

    def __str__(self):
        credit_info = f" | Credit: GH₵ {self.credit_balance:,.2f}" if self.credit_balance > 0 else ""
        return f"{self.student.email} - {self.semester} (Balance: GH₵ {self.balance:,.2f}{credit_info})"


class RefundRequest(models.Model):
    """Student request for refund of credit balance (overpayment)."""
    class Channel(models.TextChoices):
        MOMO = "momo", "Mobile Money"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CASH_CHEQUE = "cash_cheque", "Cheque / Cash at Bursary"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        APPROVED = "approved", "Approved"
        DISBURSED = "disbursed", "Disbursed / Paid"
        REJECTED = "rejected", "Rejected"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refund_requests"
    )
    statement = models.ForeignKey(
        StudentAccountStatement,
        on_delete=models.CASCADE,
        related_name="refund_requests"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="GHS")
    channel = models.CharField(max_length=30, choices=Channel.choices, default=Channel.MOMO)
    account_details = models.CharField(max_length=150, help_text="Mobile money number or bank account number & name")
    reason = models.TextField(blank=True, default="Semester fee overpayment refund")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_refunds"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    disbursement_reference = models.CharField(max_length=100, blank=True)
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund #{self.id} - {self.student.email} - GH₵ {self.amount:,.2f} ({self.status})"


class Payment(models.Model):
    """Payment transaction record across MoMo, Bank API, or Manual Deposit Slip."""
    class Channel(models.TextChoices):
        MOMO = "momo", "Mobile Money"
        BANK_API = "bank_api", "Automated Bank Collect"
        BANK_MANUAL = "bank_manual", "Bank Deposit Slip"
        BURSARY = "bursary", "Scholarship / Bursary"

    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        PENDING_VERIFICATION = "pending_verification", "Pending Verification"
        FAILED = "failed", "Failed"

    statement = models.ForeignKey(
        StudentAccountStatement,
        on_delete=models.CASCADE,
        related_name="payments"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fee_payments"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="GHS")
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.MOMO)
    provider = models.CharField(max_length=60, blank=True)  # e.g., "MTN Mobile Money", "GCB Bank Ltd"
    phone_or_account = models.CharField(max_length=60, blank=True)
    reference_number = models.CharField(max_length=100, unique=True)
    receipt_number = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.COMPLETED)
    slip_image = models.ImageField(upload_to="bank_slips/%Y/%m/", null=True, blank=True)
    notes = models.TextField(blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="verified_payments"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.receipt_number} - {self.student.email} - GH₵ {self.amount:,.2f} ({self.status})"


class FinancialHold(models.Model):
    """Academic registration hold triggered by fee arrears > GH₵ 500."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="financial_holds"
    )
    reason = models.CharField(max_length=255, default="Outstanding semester fee arrears exceeding GH₵ 500.00")
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    is_active = models.BooleanField(default=True)
    placed_at = models.DateTimeField(auto_now_add=True)
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-placed_at"]

    def clear(self):
        self.is_active = False
        self.cleared_at = timezone.now()
        self.save(update_fields=["is_active", "cleared_at"])

    def __str__(self):
        state = "ACTIVE" if self.is_active else "CLEARED"
        return f"Hold for {self.student.email} [{state}] - GH₵ {self.amount_due:,.2f}"


from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache


@receiver([post_save, post_delete], sender=FinancialHold)
def invalidate_clearance_cache_on_hold(sender, instance, **kwargs):
    if getattr(instance, "student_id", None):
        cache.delete(f"exam_clearance_status_{instance.student_id}")


@receiver([post_save, post_delete], sender=StudentAccountStatement)
def invalidate_clearance_cache_on_statement(sender, instance, **kwargs):
    if getattr(instance, "student_id", None):
        cache.delete(f"exam_clearance_status_{instance.student_id}")


@receiver([post_save, post_delete], sender=Payment)
def invalidate_clearance_cache_on_payment(sender, instance, **kwargs):
    if getattr(instance, "student_id", None):
        cache.delete(f"exam_clearance_status_{instance.student_id}")
