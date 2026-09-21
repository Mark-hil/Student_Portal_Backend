
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
        extra_fields.setdefault("role", "admin")
        return self.create_user(email, password, **extra_fields)

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        INSTRUCTOR = "instructor", "Instructor"
        STAFF = "staff", "Staff"
        FINANCE = "finance", "Finance Officer"
        ADMIN = "admin", "Admin"

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
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True)
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

    @property
    def is_student_role(self):
        return self.role == self.Role.STUDENT

    @property
    def is_instructor_role(self):
        return self.role == self.Role.INSTRUCTOR

    @property
    def is_finance_role(self):
        return self.role in (self.Role.FINANCE, self.Role.ADMIN)

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

