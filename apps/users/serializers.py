"""User serializers — registration, profile, password change."""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import UserProfile, AcademicProgressionLog
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UserProfile
        fields = [
            "enrollment_year", "graduation_year", "academic_level", "major", "gpa", "total_credits", "preferences",
            "ghana_card", "gender", "date_of_birth", "birth_place", "country_of_birth", "nationality",
            "languages_spoken", "medical_condition", "residential_address", "city", "region", "district",
            "digital_address", "guardian_name", "guardian_phone", "guardian_relationship", "registration_completed_at",
        ]


class UserSerializer(serializers.ModelSerializer):
    profile   = UserProfileSerializer(read_only=True)
    full_name = serializers.CharField(read_only=True)
    avatar    = serializers.SerializerMethodField()
    assigned_functions = serializers.ListField(child=serializers.CharField(), read_only=True)
    effective_functions = serializers.SerializerMethodField()

    is_deleted = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            "id", "email", "student_id", "moh_pin", "serial_number",
            "program", "class_name", "admission_year", "is_registered",
            "academic_status", "withdrawal_date", "withdrawal_reason", "graduation_date",
            "deleted_at", "is_deleted",
            "first_name", "last_name", "full_name",
            "role", "assigned_functions", "effective_functions",
            "avatar", "phone", "department", "bio", "is_active",
            "email_verified", "created_at", "profile",
        ]
        read_only_fields = [
            "id", "email", "role", "assigned_functions", "effective_functions",
            "email_verified", "created_at",
            "student_id", "moh_pin", "program", "class_name", "admission_year",
            "academic_status", "withdrawal_date", "withdrawal_reason", "graduation_date",
            "deleted_at", "is_deleted"
        ]

    def get_effective_functions(self, obj):
        return getattr(obj, "effective_functions", [])

    def get_is_deleted(self, obj):
        return obj.deleted_at is not None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # Defense-in-depth: only admin/staff or student themselves may see serial_number
        is_staff_or_admin = (
            request and request.user.is_authenticated and 
            (request.user.is_superuser or getattr(request.user, "normalized_role", request.user.role) in ("super_admin", "academic_officer", "admin", "staff"))
        )
        is_owner = request and request.user.is_authenticated and request.user.id == instance.id
        if not (is_staff_or_admin or is_owner):
            data.pop("serial_number", None)
        return data

    def get_avatar(self, obj):
        if not obj.avatar:
            return None
        url_str = str(obj.avatar)
        if url_str.startswith("http://") or url_str.startswith("https://"):
            return url_str
        request = self.context.get("request")
        try:
            return request.build_absolute_uri(obj.avatar.url) if request else obj.avatar.url
        except Exception:
            return url_str

    def update(self, instance, validated_data):
        profile_data = self.initial_data.get("profile")
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if profile_data and isinstance(profile_data, dict):
            profile, _ = UserProfile.objects.get_or_create(user=instance)
            if "major" in profile_data:
                profile.major = profile_data["major"]
            if "preferences" in profile_data and isinstance(profile_data["preferences"], dict):
                profile.preferences = {**profile.preferences, **profile_data["preferences"]}
            profile.save()
            instance.profile = profile

        return instance


class RegisterSerializer(serializers.Serializer):
    email      = serializers.EmailField()
    password   = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150)
    last_name  = serializers.CharField(max_length=150)
    role       = serializers.ChoiceField(choices=["student", "instructor"], default="student")

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password     = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def validate(self, data):
        user = self.context["request"].user
        if not user.check_password(data["current_password"]):
            raise serializers.ValidationError({"current_password": "Incorrect current password."})
        return data


class AdminCreateUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=6)

    class Meta:
        model = User
        fields = [
            "id", "email", "password", "first_name", "last_name", "role", 
            "department", "phone", "is_active", "program", "class_name", 
            "admission_year", "student_id", "moh_pin", "serial_number", "is_registered"
        ]

    def validate_password(self, value):
        if value:
            validate_password(value)
        return value

    def create(self, validated_data):
        from datetime import datetime
        from apps.users.services.roster_service import generate_asdam_student_id
        from apps.notifications.tasks import dispatch_welcome_notifications

        password = validated_data.pop("password", None)
        role = validated_data.get("role", User.Role.STUDENT)

        if role == User.Role.STUDENT:
            norm_prog = validated_data.get("program") or "nursing"
            norm_class = validated_data.get("class_name") or "100"
            adm_year = validated_data.get("admission_year") or datetime.now().year
            
            validated_data["program"] = norm_prog
            validated_data["class_name"] = norm_class
            validated_data["admission_year"] = adm_year
            validated_data["is_registered"] = False
            if not validated_data.get("department"):
                validated_data["department"] = "Nursing" if norm_prog == "nursing" else "Midwifery"

            if not validated_data.get("student_id"):
                validated_data["student_id"] = generate_asdam_student_id(
                    program=norm_prog,
                    class_name=norm_class,
                    year=adm_year,
                    commit=True
                )

        user = User(**validated_data)
        raw_password = password or user.serial_number or f"SN-{str(user.id)[:6].upper()}"
        if role == User.Role.STUDENT and not user.serial_number:
            user.serial_number = raw_password

        user.set_password(raw_password)
        user.save()

        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "major": user.department or "Nursing",
                "academic_level": user.class_name or "100",
                "enrollment_year": user.admission_year or datetime.now().year,
            }
        )

        # Dispatch welcome notifications with URL and credentials
        if role == User.Role.STUDENT:
            try:
                dispatch_welcome_notifications(str(user.id), raw_password)
            except Exception as e:
                logger.warning("Failed to dispatch welcome notification for user %s: %s", user.id, e)

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class MOHVerifySerializer(serializers.Serializer):
    moh_pin = serializers.CharField(required=True)
    serial_number = serializers.CharField(required=True)

    def validate(self, attrs):
        pin = str(attrs.get("moh_pin", "")).strip().upper()
        serial = str(attrs.get("serial_number", "")).strip()

        user = User.objects.filter(moh_pin__iexact=pin).first()
        if not user:
            raise serializers.ValidationError({"detail": f"MOH PIN '{pin}' was not found on the institutional admission roster."})

        # Check serial match
        matched_serial = (user.serial_number and user.serial_number.strip() == serial) or user.check_password(serial)
        if not matched_serial:
            raise serializers.ValidationError({"detail": "The Serial Number does not match the admission record for this MOH PIN."})

        attrs["user"] = user
        return attrs


class MOHRegisterSerializer(serializers.Serializer):
    moh_pin = serializers.CharField(required=True)
    serial_number = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, min_length=8)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        pin = str(attrs.get("moh_pin", "")).strip().upper()
        serial = str(attrs.get("serial_number", "")).strip()
        email = str(attrs.get("email", "")).strip().lower()

        user = User.objects.filter(moh_pin__iexact=pin).first()
        if not user:
            raise serializers.ValidationError({"detail": f"MOH PIN '{pin}' was not found on the institutional admission roster."})

        matched_serial = (user.serial_number and user.serial_number.strip() == serial) or user.check_password(serial)
        if not matched_serial:
            raise serializers.ValidationError({"detail": "The Serial Number does not match the admission record for this MOH PIN."})

        if email and email != user.email:
            if User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
                raise serializers.ValidationError({"email": "This email address is already in use by another account."})

        attrs["user"] = user
        return attrs

    def save(self):
        user = self.validated_data["user"]
        password = self.validated_data["password"]
        email = self.validated_data.get("email")
        phone = self.validated_data.get("phone")

        user.set_password(password)
        if email:
            user.email = email
            user.email_verified = True
        if phone:
            user.phone = phone

        user.is_registered = True
        user.is_active = True
        user.save()
        return user


class MultiIdentifierTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Enterprise authentication serializer supporting:
    - Email Address
    - ASDAM Student ID (e.g. ASDAM/NUR/100/26/001)
    - MOH PIN (e.g. MOH-NUR-2026-001)
    Also supports initial student sign-in using their Serial Number as temporary password.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"] = serializers.CharField(required=False)
        self.fields["username"] = serializers.CharField(required=False)

    def validate(self, attrs):
        identifier = (
            attrs.get("email") or attrs.get("username") or
            self.initial_data.get("email") or self.initial_data.get("username") or
            self.initial_data.get("student_id") or self.initial_data.get("moh_pin")
        )
        password = attrs.get("password") or self.initial_data.get("password")

        if not identifier or not password:
            raise serializers.ValidationError({"detail": "Please provide your identifier (Email, Student ID, or MOH PIN) and password."})

        identifier_clean = str(identifier).strip()
        from django.db.models import Q

        user = User.objects.filter(
            Q(email__iexact=identifier_clean) |
            Q(student_id__iexact=identifier_clean) |
            Q(moh_pin__iexact=identifier_clean)
        ).first()

        if not user:
            raise serializers.ValidationError({"detail": "No active account found matching the provided credentials."})

        is_valid = user.check_password(password)
        # Allow initial sign in for un-registered students using their serial_number
        if not is_valid and not user.is_registered and user.serial_number and user.serial_number.strip() == str(password).strip():
            is_valid = True

        if not is_valid:
            raise serializers.ValidationError({"detail": "Invalid password or credentials."})

        if not user.is_active:
            raise serializers.ValidationError({"detail": "This account is inactive or suspended. Please contact the academic office."})

        refresh = self.get_token(user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user, context=self.context).data,
        }


class StudentRegistrationCompletionSerializer(serializers.Serializer):
    """
    Mandatory student profile completion serializer based on info.txt requirements.
    Enforces validation for personal demographics, Ghana Card, contact information,
    and parent/guardian next-of-kin details.
    """
    # Personal details (info.txt)
    first_name = serializers.CharField(max_length=150, required=True)
    last_name = serializers.CharField(max_length=150, required=True)
    ghana_card = serializers.CharField(max_length=50, required=True)
    gender = serializers.CharField(max_length=20, required=True)
    date_of_birth = serializers.DateField(required=True)
    birth_place = serializers.CharField(max_length=150, required=True)
    country_of_birth = serializers.CharField(max_length=100, default="Ghana", required=False)
    nationality = serializers.CharField(max_length=100, default="Ghanaian", required=False)
    languages_spoken = serializers.CharField(max_length=255, required=False, allow_blank=True)
    medical_condition = serializers.CharField(required=False, allow_blank=True)

    # Contact information (info.txt)
    residential_address = serializers.CharField(max_length=255, required=True)
    city = serializers.CharField(max_length=100, required=True)
    region = serializers.CharField(max_length=100, required=True)
    district = serializers.CharField(max_length=100, required=True)
    digital_address = serializers.CharField(max_length=50, required=True)
    phone = serializers.CharField(max_length=30, required=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    # Parent / Guardian / Next of Kin (info.txt)
    guardian_name = serializers.CharField(max_length=150, required=True)
    guardian_phone = serializers.CharField(max_length=30, required=True)
    guardian_relationship = serializers.CharField(max_length=50, required=False, allow_blank=True)

    # Permanent Password Setup
    new_password = serializers.CharField(write_only=True, required=False, allow_blank=True, min_length=8)

    def validate_ghana_card(self, value):
        cleaned = str(value).strip().upper()
        if len(cleaned) < 5:
            raise serializers.ValidationError("Please provide a valid Ghana Card number (e.g. GHA-XXXXXXXXX-X).")
        return cleaned

    def validate_new_password(self, value):
        if value:
            validate_password(value)
        return value

    def save(self, user):
        from django.utils import timezone
        data = self.validated_data
        user.first_name = data["first_name"].strip()
        user.last_name = data["last_name"].strip()
        user.phone = data["phone"].strip()
        
        email = data.get("email")
        if email and email.strip().lower() != user.email.lower():
            clean_email = email.strip().lower()
            if User.objects.filter(email__iexact=clean_email).exclude(id=user.id).exists():
                raise serializers.ValidationError({"email": "This email address is already in use."})
            user.email = clean_email
            user.email_verified = True

        new_password = data.get("new_password")
        if new_password:
            user.set_password(new_password)

        user.is_registered = True
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.ghana_card = data["ghana_card"].strip()
        profile.gender = data["gender"].strip()
        profile.date_of_birth = data["date_of_birth"]
        profile.birth_place = data["birth_place"].strip()
        profile.country_of_birth = (data.get("country_of_birth") or "Ghana").strip()
        profile.nationality = (data.get("nationality") or "Ghanaian").strip()
        profile.languages_spoken = (data.get("languages_spoken") or "").strip()
        profile.medical_condition = (data.get("medical_condition") or "").strip()
        profile.residential_address = data["residential_address"].strip()
        profile.city = data["city"].strip()
        profile.region = data["region"].strip()
        profile.district = data["district"].strip()
        profile.digital_address = data["digital_address"].strip().upper()
        profile.guardian_name = data["guardian_name"].strip()
        profile.guardian_phone = data["guardian_phone"].strip()
        profile.guardian_relationship = (data.get("guardian_relationship") or "Parent/Guardian").strip()
        profile.registration_completed_at = timezone.now()
        profile.save()

        # Trigger registration confirmation notifications
        try:
            from apps.notifications.tasks import dispatch_registration_confirmation
            dispatch_registration_confirmation(str(user.id))
        except Exception:
            pass

        return user


class AcademicProgressionLogSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()
    performed_by_email = serializers.SerializerMethodField()
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AcademicProgressionLog
        fields = [
            "id", "student", "action", "action_display", "from_level", "to_level",
            "from_status", "to_status", "reason", "academic_year", "semester",
            "performed_by", "performed_by_name", "performed_by_email", "metadata", "created_at"
        ]
        read_only_fields = fields

    def get_performed_by_name(self, obj):
        return obj.performed_by.full_name if obj.performed_by else "System"

    def get_performed_by_email(self, obj):
        return obj.performed_by.email if obj.performed_by else None


class PromoteStudentSerializer(serializers.Serializer):
    target_level = serializers.CharField(required=False, allow_blank=True)
    academic_year = serializers.CharField(required=False, allow_blank=True)
    semester = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class DemoteStudentSerializer(serializers.Serializer):
    target_level = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=True)
    academic_year = serializers.CharField(required=False, allow_blank=True)
    semester = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class WithdrawStudentSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True)
    effective_date = serializers.DateField(required=False, allow_null=True)
    academic_year = serializers.CharField(required=False, allow_blank=True)
    semester = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ReinstateStudentSerializer(serializers.Serializer):
    target_level = serializers.CharField(required=False, allow_blank=True)
    academic_year = serializers.CharField(required=False, allow_blank=True)
    semester = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class BulkPromoteSerializer(serializers.Serializer):
    student_ids = serializers.ListField(child=serializers.UUIDField(), required=True, min_length=1)
    target_level = serializers.CharField(required=False, allow_blank=True)
    academic_year = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class HardDeleteStudentSerializer(serializers.Serializer):
    force = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True)


class AssignRoleAndFunctionsSerializer(serializers.Serializer):
    role = serializers.CharField(required=False, allow_blank=True)
    assigned_functions = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )

    def validate_role(self, value):
        if value:
            from .constants import normalize_role, RoleChoice
            normalized = normalize_role(value)
            valid_roles = [r[0] for r in RoleChoice.CHOICES]
            if normalized not in valid_roles:
                raise serializers.ValidationError(f"Invalid role '{value}'. Must be one of: {valid_roles}")
            return normalized
        return value

    def validate_assigned_functions(self, value):
        from .constants import ALL_FUNCTION_CODES
        invalid = [code for code in value if code not in ALL_FUNCTION_CODES]
        if invalid:
            raise serializers.ValidationError(f"Invalid capability codes: {invalid}")
        return value



