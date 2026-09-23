"""
Authentication and security audit signals.
Automatically logs login success, failed attempts, and logouts.
"""
from django.contrib.auth.signals import user_logged_in, user_login_failed, user_logged_out
from django.dispatch import receiver
from apps.users.models import AuditLog
from apps.users.services.audit_service import AuditService


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    AuditService.log_event(
        action="AUTH_LOGIN_SUCCESS",
        category=AuditLog.Category.AUTH,
        actor=user,
        request=request,
        status=AuditLog.Status.SUCCESS,
        target_type="User",
        target_id=str(user.id),
        target_repr=f"{user.full_name} ({user.email})",
        description=f"User successfully logged in with role '{getattr(user, 'normalized_role', user.role)}'.",
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    identifier = (
        (credentials or {}).get("email") or
        (credentials or {}).get("username") or
        (credentials or {}).get("student_id") or
        (credentials or {}).get("moh_pin") or
        "Unknown"
    )
    AuditService.log_event(
        action="AUTH_LOGIN_FAILED",
        category=AuditLog.Category.AUTH,
        actor_email=str(identifier),
        request=request,
        status=AuditLog.Status.FAILURE,
        target_type="User",
        target_repr=str(identifier),
        description=f"Authentication attempt failed for identifier '{identifier}'.",
        metadata={"attempted_identifier": str(identifier)},
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    if user and getattr(user, "is_authenticated", False):
        AuditService.log_event(
            action="AUTH_LOGOUT",
            category=AuditLog.Category.AUTH,
            actor=user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(user.id),
            target_repr=f"{user.full_name} ({user.email})",
            description="User logged out from active session.",
        )
