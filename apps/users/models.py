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
        ADMIN = "admin", "Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    student_id = models.CharField(max_length=20, unique=True, null=True, blank=True, db_index=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True)
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", null=True, blank=True)
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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["role", "is_active"]),
            models.Index(fields=["department", "role"]),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=["deleted_at", "is_active"])

    @property
    def is_student_role(self):
        return self.role == self.Role.STUDENT

    @property
    def is_instructor_role(self):
        return self.role == self.Role.INSTRUCTOR


class UserProfile(models.Model):
    """Extended profile — separated to avoid SELECT * overhead."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    enrollment_year = models.PositiveSmallIntegerField(null=True, blank=True)
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True)
    major = models.CharField(max_length=100, blank=True)
    gpa = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    total_credits = models.PositiveSmallIntegerField(default=0)
    preferences = models.JSONField(default=dict)

    class Meta:
        db_table = "user_profiles"

    def __str__(self):
        return f"Profile<{self.user.email}>"
