
"""
Custom User model.
- UUID primary key (no sequential IDs leaked)
- Role-based access control  
- Soft delete support
"""
import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "super_admin")
        return self.create_user(email, password, **extra_fields)

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        ACADEMIC_OFFICER = "academic_officer", "Academic Officer"
        HEAD_OF_DEPARTMENT = "head_of_department", "Head of Department"
        FINANCE = "finance", "Finance Officer"
        LECTURER = "lecturer", "Lecturer"
        STUDENT = "student", "Student"
        # Backward-compatible aliases
        ADMIN = "admin", "Admin (Legacy)"
        STAFF = "staff", "Staff (Legacy)"
        INSTRUCTOR = "instructor", "Instructor (Legacy)"
        SUPER_ADMIN_HYPHEN = "super-admin", "Super Admin (Alias)"
        ACADEMIC_OFFICER_HYPHEN = "academic-officer", "Academic Officer (Alias)"
        DEPARTMENTAL_HEAD = "departmental-head", "Departmental Head (Alias)"
        HEAD_OF_DEPARTMENT_HYPHEN = "head-of-department", "Head of Department (Alias)"
        FINANCE_OFFICER = "finance-officer", "Finance Officer (Alias)"
        FINANCE_OFFICER_UNDERSCORE = "finance_officer", "Finance Officer (Alias)"

    class AcademicStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        PROBATION = "probation", "Academic Probation"
        REPEATING = "repeating", "Repeating"
        WITHDRAWN = "withdrawn", "Withdrawn"
        SUSPENDED = "suspended", "Suspended"
        GRADUATED = "graduated", "Graduated"
        DELETED = "deleted", "Deleted / Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    student_id = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)
    moh_pin = models.CharField(max_length=60, unique=True, null=True, blank=True, db_index=True)
    serial_number = models.CharField(max_length=60, null=True, blank=True, db_index=True)
    program = models.CharField(max_length=30, choices=[("nursing", "Nursing"), ("midwifery", "Midwifery")], blank=True, default="")
    class_name = models.CharField(max_length=50, blank=True, default="100")
    admission_year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_registered = models.BooleanField(default=False)
    academic_status = models.CharField(
        max_length=20,
        choices=AcademicStatus.choices,
        default=AcademicStatus.ACTIVE,
        db_index=True,
    )
    withdrawal_date = models.DateField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)
    graduation_date = models.DateField(null=True, blank=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.STUDENT, db_index=True)
    assigned_functions = models.JSONField(default=list, blank=True)
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", null=True, blank=True, max_length=500)
    phone = models.CharField(max_length=20, blank=True)
    department = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    objects = UserManager()
    all_objects = models.Manager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["role", "is_active"]),
            models.Index(fields=["department", "role"]),
            models.Index(fields=["role", "academic_status"]),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.is_active = False
        self.academic_status = self.AcademicStatus.DELETED
        self.save(update_fields=["deleted_at", "is_active", "academic_status"])

    def restore(self):
        self.deleted_at = None
        self.is_active = True
        self.academic_status = self.AcademicStatus.ACTIVE
        self.save(update_fields=["deleted_at", "is_active", "academic_status"])

    def save(self, *args, **kwargs):
        if self.role:
            from .constants import normalize_role
            self.role = normalize_role(self.role)
        super().save(*args, **kwargs)

    @property
    def normalized_role(self):
        from .constants import normalize_role
        return normalize_role(self.role)

    @property
    def effective_functions(self):
        from .constants import get_effective_functions
        return get_effective_functions(self.role, self.assigned_functions)

    def has_portal_permission(self, function_code: str) -> bool:
        if not self.is_active:
            return False
        if self.is_superuser or self.normalized_role == "super_admin":
            return True
        return function_code in self.effective_functions

    @property
    def is_super_admin(self):
        return self.is_superuser or self.normalized_role == "super_admin"

    @property
    def is_academic_officer(self):
        return self.normalized_role == "academic_officer" or self.is_super_admin

    @property
    def is_hod(self):
        return self.normalized_role == "head_of_department" or self.is_super_admin

    @property
    def is_finance_role(self):
        return self.normalized_role == "finance" or self.is_super_admin

    @property
    def is_lecturer_role(self):
        return self.normalized_role == "lecturer" or self.is_super_admin

    @property
    def is_instructor_role(self):
        return self.is_lecturer_role

    @property
    def is_student_role(self):
        return self.normalized_role == "student"

    @property
    def academic_level(self):
        if hasattr(self, "profile") and self.profile and self.profile.academic_level:
            return self.profile.academic_level
        return "100"


class UserProfile(models.Model):
    """Extended profile — separated to avoid SELECT * overhead."""
    LEVEL_CHOICES = [
        ("100", "Level 100 (Freshmen)"),
        ("200", "Level 200 (Sophomores)"),
        ("300", "Level 300 (Juniors)"),
        ("400", "Level 400 (Seniors)"),
        ("postgraduate", "Postgraduate"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    # Academic & Program Details
    academic_level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default="100", blank=True)
    enrollment_year = models.PositiveSmallIntegerField(null=True, blank=True)
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True)
    major = models.CharField(max_length=100, blank=True)
    gpa = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    total_credits = models.PositiveSmallIntegerField(default=0)
    preferences = models.JSONField(default=dict)

    # Personal Details (info.txt)
    ghana_card = models.CharField(max_length=50, blank=True, db_index=True)
    gender = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    birth_place = models.CharField(max_length=150, blank=True)
    country_of_birth = models.CharField(max_length=100, blank=True, default="Ghana")
    nationality = models.CharField(max_length=100, blank=True, default="Ghanaian")
    languages_spoken = models.CharField(max_length=255, blank=True)
    medical_condition = models.TextField(blank=True)

    # Contact Information & Address (info.txt)
    residential_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    digital_address = models.CharField(max_length=50, blank=True)  # Ghana Post GPS

    # Parent / Guardian / Next of Kin (info.txt)
    guardian_name = models.CharField(max_length=150, blank=True)
    guardian_phone = models.CharField(max_length=30, blank=True)
    guardian_relationship = models.CharField(max_length=50, blank=True)

    # Registration Audit
    registration_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_profiles"

    def __str__(self):
        return f"Profile<{self.user.email}>"


class IDSequence(models.Model):
    """
    Atomic sequence counter for institutional Student IDs.
    Prevents race conditions using database row-level locking.
    """
    program = models.CharField(max_length=30, db_index=True)
    class_name = models.CharField(max_length=50, blank=True, default="")
    year = models.PositiveSmallIntegerField(db_index=True)
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "id_sequences"
        unique_together = ("program", "class_name", "year")

    def __str__(self):
        return f"Seq<{self.program}-{self.class_name}-{self.year}: {self.last_number}>"


class AcademicProgressionLog(models.Model):
    """
    Immutable audit trail for student academic progression, retention,
    withdrawals, reinstatements, and lifecycle events.
    """
    class ActionType(models.TextChoices):
        PROMOTION = "promotion", "Promotion"
        DEMOTION = "demotion", "Demotion"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        REINSTATEMENT = "reinstatement", "Reinstatement"
        GRADUATION = "graduation", "Graduation"
        STATUS_CHANGE = "status_change", "Status Change"
        SOFT_DELETE = "soft_delete", "Soft Delete"
        RESTORE = "restore", "Restore"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name="progression_logs")
    action = models.CharField(max_length=30, choices=ActionType.choices, db_index=True)
    from_level = models.CharField(max_length=50, blank=True)
    to_level = models.CharField(max_length=50, blank=True)
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30, blank=True)
    reason = models.TextField(blank=True)
    academic_year = models.CharField(max_length=30, blank=True)
    semester = models.CharField(max_length=30, blank=True)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_progressions"
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "academic_progression_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["student", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} for {self.student.email}: {self.from_level} -> {self.to_level} at {self.created_at}"


class AuditLog(models.Model):
    """
    Immutable, append-only security and operational audit trail for institutional compliance.
    Records all authentication events, administrative actions, role assignments,
    and sensitive data modifications with actor snapshots and change diffs.
    """
    class Category(models.TextChoices):
        AUTH = "auth", "Authentication & Session"
        USER_MANAGEMENT = "user_management", "User & Access Management"
        ACADEMICS = "academics", "Academics & Grading"
        FINANCIALS = "financials", "Financials & Billing"
        SECURITY = "security", "Security & System Shielding"
        SYSTEM = "system", "System & Data Maintenance"

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"
        WARNING = "warning", "Warning"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    # Actor attribution (with immutable historical snapshot in case user is deleted or altered)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs"
    )
    actor_email = models.CharField(max_length=255, blank=True, db_index=True)
    actor_role = models.CharField(max_length=50, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    # Action taxonomy
    action = models.CharField(max_length=100, db_index=True)
    action_category = models.CharField(
        max_length=40,
        choices=Category.choices,
        default=Category.SYSTEM,
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUCCESS,
        db_index=True
    )

    # Target entity
    target_type = models.CharField(max_length=100, blank=True, db_index=True)
    target_id = models.CharField(max_length=100, blank=True, db_index=True)
    target_repr = models.CharField(max_length=255, blank=True)

    # Audit narrative and structured diff
    description = models.TextField(blank=True)
    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp", "action_category"]),
            models.Index(fields=["actor_email", "timestamp"]),
            models.Index(fields=["action", "status"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {self.actor_email or 'Anonymous'} -> {self.action} ({self.status})"

    def save(self, *args, **kwargs):
        # Strict immutability guarantee: once written to the DB, records can NEVER be modified
        if not self._state.adding and self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise RuntimeError("AuditLog records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Strict immutability guarantee: audit records can NEVER be deleted
        raise RuntimeError("AuditLog records are permanent and cannot be deleted.")


class PasswordResetToken(models.Model):
    """Secure OTP token for self-service password reset via SMS or Email."""

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        EMAIL = "email", "Email"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    token_hash = models.CharField(max_length=128, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.SMS)
    destination = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    is_used = models.BooleanField(default=False, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "password_reset_tokens"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_used", "expires_at"]),
            models.Index(fields=["token_hash", "is_used"]),
        ]

    def __str__(self):
        return f"PasswordResetToken for {self.user.email} via {self.channel} (used={self.is_used})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_locked(self) -> bool:
        return self.attempts >= self.max_attempts


