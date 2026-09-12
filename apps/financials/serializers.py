"""Serializers for Student Financials & Billing."""
from decimal import Decimal
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import SemesterFeeStructure, StudentAccountStatement, Payment, FinancialHold

User = get_user_model()


class PaymentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.ReadOnlyField(source="student.email")
    student_index = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "receipt_number",
            "amount",
            "currency",
            "channel",
            "provider",
            "phone_or_account",
            "reference_number",
            "status",
            "slip_image",
            "notes",
            "created_at",
            "verified_at",
            "student_name",
            "student_email",
            "student_index",
        ]

    def get_student_name(self, obj):
        name = f"{obj.student.first_name} {obj.student.last_name}".strip()
        return name or obj.student.email

    def get_student_index(self, obj):
        return getattr(obj.student, "student_id", None) or f"UG-{str(obj.student.id)[:8].upper()}"


class StudentAccountStatementSerializer(serializers.ModelSerializer):
    payments = PaymentSerializer(many=True, read_only=True)
    has_active_hold = serializers.SerializerMethodField()
    active_hold_reason = serializers.SerializerMethodField()
    student_name = serializers.SerializerMethodField()
    student_index = serializers.SerializerMethodField()

    class Meta:
        model = StudentAccountStatement
        fields = [
            "id",
            "semester",
            "academic_fee",
            "ict_library_fee",
            "src_dues",
            "examination_fee",
            "bursary_aid",
            "academic_level",
            "total_billed",
            "total_paid",
            "balance",
            "currency",
            "status",
            "due_date",
            "has_active_hold",
            "active_hold_reason",
            "student_name",
            "student_index",
            "payments",
            "created_at",
            "updated_at",
        ]

    def get_has_active_hold(self, obj):
        return FinancialHold.objects.filter(student=obj.student, is_active=True).exists()

    def get_active_hold_reason(self, obj):
        hold = FinancialHold.objects.filter(student=obj.student, is_active=True).first()
        return hold.reason if hold else None

    def get_student_name(self, obj):
        name = f"{obj.student.first_name} {obj.student.last_name}".strip()
        return name or obj.student.email

    def get_student_index(self, obj):
        return getattr(obj.student, "student_id", None) or f"UG-{str(obj.student.id)[:8].upper()}"


class SemesterFeeStructureSerializer(serializers.ModelSerializer):
    total_fee = serializers.ReadOnlyField(source="total_semester_fee")

    class Meta:
        model = SemesterFeeStructure
        fields = [
            "id",
            "semester",
            "academic_level",
            "level_title",
            "academic_fee",
            "ict_library_fee",
            "src_dues",
            "examination_fee",
            "total_fee",
            "due_date",
            "is_active",
            "created_at",
            "updated_at",
        ]


class MoMoPaymentRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"))
    provider = serializers.ChoiceField(choices=["MTN Mobile Money", "Telecel Cash", "AT Money"])
    phone = serializers.CharField(max_length=20)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)


class ManualBankSlipRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"))
    bank_name = serializers.CharField(max_length=60)
    slip_ref = serializers.CharField(max_length=100)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)


class BankNotificationRequestSerializer(serializers.Serializer):
    """Payload sent by Partner Bank Collect API (GCB, Ecobank, Zenith, CalBank)."""
    student_id = serializers.CharField(max_length=100)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"))
    bank_name = serializers.CharField(max_length=60)
    teller_ref = serializers.CharField(max_length=100, required=False)
    bank_reference = serializers.CharField(max_length=100, required=False)
    branch = serializers.CharField(max_length=100, required=False, allow_blank=True)
    depositor_name = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, attrs):
        ref = attrs.get("teller_ref") or attrs.get("bank_reference")
        if not ref:
            raise serializers.ValidationError({"teller_ref": "This field is required (provide teller_ref or bank_reference)."})
        attrs["teller_ref"] = ref
        return attrs


class BankStudentLookupSerializer(serializers.Serializer):
    """Response returned when bank teller queries student ID."""
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    program = serializers.CharField()
    semester = serializers.CharField()
    total_billed = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_paid = serializers.DecimalField(max_digits=10, decimal_places=2)
    balance_due = serializers.DecimalField(max_digits=10, decimal_places=2)
    status = serializers.CharField()
