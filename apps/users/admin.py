from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = ["email", "full_name", "student_id", "role", "is_active", "email_verified", "created_at"]
    list_filter = ["role", "is_active", "email_verified", "department"]
    search_fields = ["email", "first_name", "last_name", "student_id"]
    ordering = ["-created_at"]
    readonly_fields = ["created_at", "updated_at", "last_login", "last_login_ip"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "phone", "date_of_birth", "bio", "avatar")}),
        ("Academic", {"fields": ("student_id", "role", "department")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "email_verified", "groups", "user_permissions")}),
        ("Audit", {"fields": ("created_at", "updated_at", "last_login", "last_login_ip", "deleted_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
        }),
    )
