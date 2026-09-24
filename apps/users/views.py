"""User auth and profile views."""
import logging
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    RegisterSerializer, UserSerializer, ChangePasswordSerializer,
    MOHVerifySerializer, MOHRegisterSerializer, MultiIdentifierTokenObtainPairSerializer,
    StudentRegistrationCompletionSerializer, AcademicProgressionLogSerializer,
    PromoteStudentSerializer, DemoteStudentSerializer, WithdrawStudentSerializer,
    ReinstateStudentSerializer, BulkPromoteSerializer, HardDeleteStudentSerializer,
    AssignRoleAndFunctionsSerializer, AuditLogSerializer,
    PasswordResetRequestSerializer, PasswordResetVerifySerializer, PasswordResetConfirmSerializer,
)
import hashlib
import secrets
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from apps.notifications.sms import send_sms
from .models import AuditLog, PasswordResetToken
from .services.audit_service import AuditService
from .services.roster_service import process_roster_csv, generate_sample_csv_template
from core.permissions import IsAdminOrStaff

logger = logging.getLogger(__name__)
User = get_user_model()


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def _mask_destination(dest: str, channel: str) -> str:
    if channel == "email" or "@" in dest:
        parts = dest.split("@")
        name = parts[0]
        domain = parts[1] if len(parts) > 1 else ""
        masked_name = name[0] + "••••" + (name[-1] if len(name) > 1 else "")
        return f"{masked_name}@{domain}"
    else:
        if len(dest) >= 7:
            return dest[:3] + "••••" + dest[-3:]
        return dest[:2] + "••••"


def _find_user_by_identifier(identifier: str):
    identifier = identifier.strip()
    return User.objects.filter(
        Q(email__iexact=identifier) |
        Q(student_id__iexact=identifier) |
        Q(phone=identifier) |
        Q(moh_pin__iexact=identifier)
    ).first()


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/
    Multi-identifier authentication supporting Email, Student ID, or MOH PIN.
    Supports students logging in with their initial Serial Number as temporary password.
    """
    serializer_class = MultiIdentifierTokenObtainPairSerializer


class VerifyMOHView(APIView):
    """
    POST /api/v1/auth/verify-moh/
    Verify student MOH PIN and Serial Number before portal account activation.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MOHVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        return Response({
            "status": "verified",
            "student_id": user.student_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name,
            "moh_pin": user.moh_pin,
            "program": user.program,
            "program_label": "Nursing" if user.program == "nursing" else "Midwifery",
            "class_name": user.class_name,
            "admission_year": user.admission_year,
            "email": user.email,
            "is_registered": user.is_registered,
        }, status=status.HTTP_200_OK)


class RegisterMOHView(APIView):
    """
    POST /api/v1/auth/register-moh/
    Activate student account using verified MOH PIN and Serial Number.
    Sets personal email, password, and issues JWT tokens.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MOHRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        logger.info("MOH Student Activated: %s [%s] (%s)", user.full_name, user.student_id, user.program)
        return Response({
            "status": "success",
            "message": "Student portal account activated successfully.",
            "user": UserSerializer(user, context={"request": request}).data,
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
        }, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    """
    POST /api/v1/auth/password-reset/request/
    Initiate self-service password reset.
    Finds account by Student ID, Email, Phone, or MOH PIN, generates 6-digit OTP,
    hashes it, stores it, and dispatches via SMS (Arkesel v2) or Email.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        channel = serializer.validated_data.get("channel", "sms")

        user = _find_user_by_identifier(identifier)
        if not user:
            return Response({
                "error": "not_found",
                "detail": "No active account found matching the provided identifier."
            }, status=status.HTTP_404_NOT_FOUND)

        if not user.is_active:
            return Response({
                "error": "account_inactive",
                "detail": "This account is inactive. Please contact the ASDAM portal administrator."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Rate limiting: max 5 requests in 15 minutes
        recent_cutoff = timezone.now() - timedelta(minutes=15)
        recent_requests = PasswordResetToken.objects.filter(
            user=user,
            created_at__gte=recent_cutoff
        ).count()
        if recent_requests >= 5:
            return Response({
                "error": "rate_limited",
                "detail": "Too many password reset requests. Please wait 15 minutes before requesting again."
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Determine destination
        if channel == "sms":
            if not user.phone:
                channel = "email"
                destination = user.email
            else:
                destination = user.phone
        else:
            channel = "email"
            destination = user.email

        # Invalidate any previously unexpired unused tokens
        PasswordResetToken.objects.filter(user=user, is_used=False).update(is_used=True)

        # Generate 6-digit code
        raw_code = f"{secrets.randbelow(900000) + 100000}"
        token_hash = _hash_otp(raw_code)
        expires_at = timezone.now() + timedelta(minutes=15)

        client_ip = request.META.get("HTTP_X_FORWARDED_FOR")
        if client_ip:
            client_ip = client_ip.split(",")[0].strip()
        else:
            client_ip = request.META.get("REMOTE_ADDR")

        PasswordResetToken.objects.create(
            user=user,
            token_hash=token_hash,
            channel=channel,
            destination=destination,
            expires_at=expires_at,
            ip_address=client_ip,
        )

        # Dispatch message
        if channel == "sms":
            sms_text = f"Your ASDAM Student Portal password reset code is: {raw_code}. Valid for 15 minutes. Do not share this code."
            try:
                send_sms(
                    phone=destination,
                    message=sms_text,
                    sender_id="ASDAM",
                    purpose="password_reset",
                    recipient_name=user.full_name
                )
            except Exception as e:
                logger.error("Failed to dispatch password reset SMS to %s: %s", destination, e)
        else:
            email_body = (
                f"Dear {user.first_name},\n\n"
                f"We received a request to reset your ASDAM Student Portal password.\n\n"
                f"Your 6-digit password reset code is:\n\n"
                f"   {raw_code}\n\n"
                f"This code will expire in 15 minutes.\n"
                f"If you did not request a password reset, please contact the ASDAM ICT Directorate immediately.\n\n"
                f"Best regards,\n"
                f"ASDAM ICT Directorate"
            )
            try:
                send_mail(
                    subject="ASDAM Portal — Password Reset Verification Code",
                    message=email_body,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@asdam.edu.gh"),
                    recipient_list=[destination],
                    fail_silently=False,
                )
            except Exception as e:
                logger.error("Failed to send password reset email to %s: %s", destination, e)

        logger.info("Password reset code generated and dispatched for %s via %s", user.email, channel)
        return Response({
            "status": "success",
            "message": f"Password reset verification code has been sent via {channel.upper()}.",
            "channel": channel,
            "masked_destination": _mask_destination(destination, channel),
        }, status=status.HTTP_200_OK)


class PasswordResetVerifyView(APIView):
    """
    POST /api/v1/auth/password-reset/verify/
    Verify that the 6-digit code is valid and unexpired before asking user for new passwords.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        code = serializer.validated_data["code"]

        user = _find_user_by_identifier(identifier)
        if not user:
            return Response({"error": "not_found", "detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

        reset_token = PasswordResetToken.objects.filter(
            user=user,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).order_by("-created_at").first()

        if not reset_token:
            return Response({
                "error": "expired",
                "detail": "Verification code has expired or was not requested. Please request a new code."
            }, status=status.HTTP_400_BAD_REQUEST)

        if reset_token.is_locked:
            return Response({
                "error": "locked",
                "detail": "Maximum verification attempts exceeded. Please request a new code."
            }, status=status.HTTP_400_BAD_REQUEST)

        code_hash = _hash_otp(code)
        if reset_token.token_hash != code_hash:
            reset_token.attempts += 1
            reset_token.save(update_fields=["attempts"])
            remaining = max(0, reset_token.max_attempts - reset_token.attempts)
            return Response({
                "error": "invalid_code",
                "detail": f"Invalid verification code. {remaining} attempt(s) remaining."
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "status": "valid",
            "message": "Verification code is valid. You may now choose your new password."
        }, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    """
    POST /api/v1/auth/password-reset/confirm/
    Validate 6-digit OTP code, set new password, log audit event, and return auth tokens.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        code = serializer.validated_data["code"]
        new_password = serializer.validated_data["new_password"]

        user = _find_user_by_identifier(identifier)
        if not user:
            return Response({"error": "not_found", "detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

        reset_token = PasswordResetToken.objects.filter(
            user=user,
            is_used=False,
            expires_at__gt=timezone.now(),
        ).order_by("-created_at").first()

        if not reset_token:
            return Response({
                "error": "expired",
                "detail": "Verification code has expired or was not requested. Please request a new code."
            }, status=status.HTTP_400_BAD_REQUEST)

        if reset_token.is_locked:
            return Response({
                "error": "locked",
                "detail": "Maximum verification attempts exceeded. Please request a new code."
            }, status=status.HTTP_400_BAD_REQUEST)

        code_hash = _hash_otp(code)
        if reset_token.token_hash != code_hash:
            reset_token.attempts += 1
            reset_token.save(update_fields=["attempts"])
            remaining = max(0, reset_token.max_attempts - reset_token.attempts)
            return Response({
                "error": "invalid_code",
                "detail": f"Invalid verification code. {remaining} attempt(s) remaining."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Set new password
        user.set_password(new_password)
        user.save(update_fields=["password"])

        # Mark token as used
        reset_token.is_used = True
        reset_token.save(update_fields=["is_used"])

        # Audit log
        AuditService.log_event(
            action="USER_PASSWORD_RESET",
            category=AuditLog.Category.AUTH,
            actor=user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(user.id),
            target_repr=f"{user.full_name} ({user.email})",
            description=f"User '{user.email}' reset account password via {reset_token.channel.upper()} OTP verification.",
            metadata={"channel": reset_token.channel, "destination": reset_token.destination},
        )

        # Security confirmation notice
        if reset_token.channel == "sms" and reset_token.destination:
            try:
                send_sms(
                    phone=reset_token.destination,
                    message="Security Alert: Your ASDAM Portal password was successfully reset. If this was not you, contact IT Support immediately.",
                    sender_id="ASDAM",
                    purpose="security_alert",
                    recipient_name=user.full_name,
                )
            except Exception as e:
                logger.warning("Could not send SMS security alert: %s", e)
        elif user.email:
            try:
                send_mail(
                    subject="ASDAM Portal — Password Reset Confirmation",
                    message=f"Dear {user.first_name},\n\nYour ASDAM Student Portal password was successfully reset on {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}.\n\nIf you did not perform this action, please alert IT Support immediately.\n\nBest regards,\nASDAM ICT Directorate",
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@asdam.edu.gh"),
                    recipient_list=[user.email],
                    fail_silently=True,
                )
            except Exception as e:
                logger.warning("Could not send email security alert: %s", e)

        refresh = RefreshToken.for_user(user)
        logger.info("Password successfully reset for %s [%s]", user.email, user.student_id)
        return Response({
            "status": "success",
            "message": "Your password has been successfully reset. You can now sign in.",
            "user": UserSerializer(user, context={"request": request}).data,
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        }, status=status.HTTP_200_OK)


class RegisterView(generics.CreateAPIView):
    """POST /api/v1/auth/register/ — create account, return JWT pair + user."""
    permission_classes = [AllowAny]
    serializer_class   = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        logger.info("Registered: %s role=%s", user.email, user.role)
        return Response({
            "user":   UserSerializer(user).data,
            "tokens": {
                "access":  str(refresh.access_token),
                "refresh": str(refresh),
            },
        }, status=status.HTTP_201_CREATED)


class LogoutView(APIView):
    """POST /api/v1/auth/logout/ — blacklist refresh token."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except TokenError:
            pass  # already invalid — that's fine
        return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)


class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/users/me/ — current user profile."""
    permission_classes = [IsAuthenticated]
    serializer_class   = UserSerializer

    def get_object(self):
        return self.request.user


class CompleteRegistrationView(APIView):
    """
    POST /api/v1/users/me/complete-registration/
    Allows authenticated students to submit mandatory profile registration
    according to info.txt requirements, unlocking their student portal.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        serializer = StudentRegistrationCompletionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        updated_user = serializer.save(user=user)
        refresh = RefreshToken.for_user(updated_user)
        logger.info("Student Registration Completed: %s [%s]", updated_user.full_name, updated_user.student_id)
        return Response({
            "status": "success",
            "message": "Student profile registration completed successfully. Full portal access unlocked.",
            "user": UserSerializer(updated_user, context={"request": request}).data,
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        }, status=status.HTTP_200_OK)


class ChangePasswordView(APIView):

    """POST /api/v1/users/me/change-password/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        logger.info("Password changed: %s", request.user.email)
        AuditService.log_event(
            action="USER_PASSWORD_CHANGED",
            category=AuditLog.Category.AUTH,
            actor=request.user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(request.user.id),
            target_repr=f"{request.user.full_name} ({request.user.email})",
            description=f"User '{request.user.email}' updated account password.",
        )
        return Response({"detail": "Password updated successfully."})


class AvatarUploadView(APIView):
    """POST /api/v1/users/me/avatar/ — upload user profile picture to Cloudinary folder uniportal-profile picture."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        avatar_file = request.FILES.get("avatar") or request.FILES.get("file")
        if not avatar_file:
            return Response({"error": "no_file", "detail": "No image file provided."}, status=status.HTTP_400_BAD_REQUEST)

        if avatar_file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            return Response({"error": "invalid_type", "detail": "Only JPEG, PNG, WEBP, and GIF images are allowed."}, status=status.HTTP_400_BAD_REQUEST)

        if avatar_file.size > 5 * 1024 * 1024:
            return Response({"error": "file_too_large", "detail": "Avatar image size must be under 5 MB."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        cloudinary_url = None

        try:
            import os
            import cloudinary
            import cloudinary.uploader
            from django.conf import settings

            cloud_name = getattr(settings, "CLOUDINARY_STORAGE", {}).get("CLOUD_NAME") or os.environ.get("CLOUDINARY_CLOUD_NAME")
            api_key = getattr(settings, "CLOUDINARY_STORAGE", {}).get("API_KEY") or os.environ.get("CLOUDINARY_API_KEY")
            api_secret = getattr(settings, "CLOUDINARY_STORAGE", {}).get("API_SECRET") or os.environ.get("CLOUDINARY_API_SECRET")

            if cloud_name:
                if api_key and api_secret:
                    cloudinary.config(
                        cloud_name=cloud_name,
                        api_key=api_key,
                        api_secret=api_secret,
                        secure=True,
                    )
                upload_result = cloudinary.uploader.upload(
                    avatar_file,
                    folder=getattr(settings, "CLOUDINARY_PROFILE_FOLDER", "uniportal-profile picture"),
                    public_id=f"user_{user.id}_avatar",
                    overwrite=True,
                    resource_type="image",
                )
                cloudinary_url = upload_result.get("secure_url") or upload_result.get("url")
        except Exception as e:
            logger.warning("Cloudinary upload failed or not configured, falling back to standard storage: %s", e)

        if cloudinary_url:
            user.avatar = cloudinary_url
            user.save(update_fields=["avatar"])
        else:
            user.avatar = avatar_file
            user.save(update_fields=["avatar"])

        return Response(UserSerializer(user, context={"request": request}).data, status=status.HTTP_200_OK)


class UserViewSet(viewsets.ModelViewSet):
    """Admin endpoint to manage users."""
    permission_classes = [IsAdminOrStaff]

    def get_object(self):
        # Allow looking up soft-deleted users for restore or permanent deletion actions
        if self.action in ("restore", "permanent_delete", "progression_history") or self.request.query_params.get("include_deleted") in ("true", "1"):
            queryset = User.all_objects.all()
            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
            from django.shortcuts import get_object_or_404
            obj = get_object_or_404(queryset, **filter_kwargs)
            self.check_object_permissions(self.request, obj)
            if obj.is_super_admin and not (self.request.user and getattr(self.request.user, "is_super_admin", False)):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Permission denied: Super Administrator accounts are restricted.")
            return obj
        obj = super().get_object()
        if obj.is_super_admin and not (self.request.user and getattr(self.request.user, "is_super_admin", False)):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Permission denied: Super Administrator accounts are restricted.")
        return obj

    def get_queryset(self):
        academic_status = self.request.query_params.get("academic_status") or self.request.query_params.get("status")
        include_deleted = self.request.query_params.get("include_deleted", "").lower() in ("true", "1")

        if academic_status == "deleted" or include_deleted:
            qs = User.all_objects.all().order_by("-created_at")
        else:
            qs = User.objects.all().order_by("-created_at")

        # Shield Super Administrator accounts from non-superadmin actors
        user = getattr(self.request, "user", None)
        if not (user and getattr(user, "is_super_admin", False)):
            qs = qs.exclude(role="super_admin").exclude(is_superuser=True)

        if academic_status:
            if academic_status == "deleted":
                qs = qs.filter(deleted_at__isnull=False)
            elif academic_status == "active":
                qs = qs.filter(deleted_at__isnull=True, is_active=True, academic_status="active")
            else:
                qs = qs.filter(academic_status=academic_status)

        role = self.request.query_params.get("role")
        if role and role != "all":
            from .constants import normalize_role
            from django.db.models import Q
            norm_role = normalize_role(role)
            qs = qs.filter(Q(role=role) | Q(role=norm_role))

        user_type = self.request.query_params.get("user_type")
        if user_type == "student":
            qs = qs.filter(role="student")
        elif user_type in ("staff", "faculty"):
            qs = qs.exclude(role="student")

        department = self.request.query_params.get("department")
        if department:
            from django.db.models import Q
            qs = qs.filter(Q(department__icontains=department) | Q(profile__major__icontains=department))
        elif user and getattr(user, "is_hod", False) and not getattr(user, "is_super_admin", False) and user_type in ("staff", "faculty"):
            # HOD viewing staff should default to their department
            if user.department:
                qs = qs.filter(department__icontains=user.department)

        program = self.request.query_params.get("program")
        if program:
            qs = qs.filter(program=program)
        is_registered = self.request.query_params.get("is_registered")
        if is_registered is not None and is_registered != "":
            qs = qs.filter(is_registered=is_registered.lower() in ("true", "1"))
        class_name = self.request.query_params.get("class_name")
        if class_name:
            qs = qs.filter(class_name__iexact=class_name)

        search = self.request.query_params.get("search")
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(student_id__icontains=search) |
                Q(moh_pin__icontains=search)
            )
        return qs

    def destroy(self, request, *args, **kwargs):
        """Default DELETE performs a safe soft-delete / archive to trash."""
        target_user = self.get_object()
        if target_user.is_super_admin and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can delete a Super Administrator account."},
                status=status.HTTP_403_FORBIDDEN
            )
        if target_user == request.user and target_user.is_super_admin:
            return Response(
                {"detail": "Security violation: Super Administrators cannot delete their own active account."},
                status=status.HTTP_400_BAD_REQUEST
            )
        reason = request.data.get("reason") or request.query_params.get("reason") or "Deleted via management console"
        from apps.users.services.progression_service import soft_delete_student
        result = soft_delete_student(target_user, reason=reason, actor=request.user)
        AuditService.log_event(
            action="USER_DELETED",
            category=AuditLog.Category.USER_MANAGEMENT,
            actor=request.user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(target_user.id),
            target_repr=f"{target_user.full_name} ({target_user.email})",
            description=f"User account '{target_user.email}' was archived/soft-deleted. Reason: {reason}",
            metadata={"reason": reason},
        )
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="upload-moh-roster")
    def upload_moh_roster(self, request):
        """
        Upload student roster with MOH PIN and Serial Number.
        Generates ASDAM Student IDs for Nursing and Midwifery students.
        """
        csv_file = request.FILES.get("file") or request.FILES.get("csv_file")
        if not csv_file:
            return Response(
                {"detail": "No file uploaded. Please upload a CSV roster or Excel file."},
                status=status.HTTP_400_BAD_REQUEST
            )

        default_program = request.data.get("program", "nursing").lower()
        default_class = request.data.get("class_name", "NAC 26").strip()
        default_year = int(request.data.get("admission_year", 2026))
        dry_run = str(request.data.get("dry_run", "")).lower() in ("true", "1")

        try:
            result = process_roster_csv(
                csv_file=csv_file,
                default_program=default_program,
                default_class=default_class,
                default_year=default_year,
                dry_run=dry_run,
                uploader=request.user,
            )
            is_success = result.get("success") and (result.get("imported_count", 0) > 0 or (dry_run and result.get("total_rows", 0) > 0))
            if not is_success:
                errors_list = result.get("errors") or []
                if errors_list and errors_list[0].get("error"):
                    first_err = errors_list[0].get("error")
                else:
                    first_err = "No new student records were imported. All records in this file may already be registered."
                result["detail"] = first_err
                return Response(result, status=status.HTTP_400_BAD_REQUEST)

            AuditService.log_event(
                action="ROSTER_UPLOADED",
                category=AuditLog.Category.USER_MANAGEMENT,
                actor=request.user,
                request=request,
                status=AuditLog.Status.SUCCESS,
                target_type="StudentRoster",
                target_repr=getattr(csv_file, "name", "roster.csv"),
                description=f"Processed admissions roster '{getattr(csv_file, 'name', 'roster.csv')}': {result.get('imported_count', 0)} new students enrolled, {result.get('updated_count', 0)} updated.",
                metadata={
                    "filename": getattr(csv_file, "name", "roster.csv"),
                    "imported_count": result.get("imported_count", 0),
                    "updated_count": result.get("updated_count", 0),
                    "total_rows": result.get("total_rows", 0),
                    "dry_run": dry_run,
                },
            )
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Failed to process MOH roster: %s", e)
            return Response(
                {"detail": f"An error occurred while processing the roster: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["get"], url_path="moh-template")
    def moh_template(self, request):
        """Download standard CSV template for MOH student roster upload."""
        from django.http import HttpResponse
        csv_content = generate_sample_csv_template()
        response = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="asdam_moh_student_roster_template.csv"'
        return response

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            from .serializers import AdminCreateUserSerializer
            return AdminCreateUserSerializer
        return UserSerializer

    def create(self, request, *args, **kwargs):
        from .constants import normalize_role
        req_role = normalize_role(request.data.get("role", ""))
        if req_role == "super_admin" and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can create Super Administrator accounts."},
                status=status.HTTP_403_FORBIDDEN
            )
        response = super().create(request, *args, **kwargs)
        if response.status_code == status.HTTP_201_CREATED and "id" in response.data:
            AuditService.log_event(
                action="USER_CREATED",
                category=AuditLog.Category.USER_MANAGEMENT,
                actor=request.user,
                request=request,
                status=AuditLog.Status.SUCCESS,
                target_type="User",
                target_id=str(response.data["id"]),
                target_repr=f"{response.data.get('full_name')} ({response.data.get('email')})",
                description=f"Created user account '{response.data.get('email')}' with role '{response.data.get('role')}'.",
                changes={"after": response.data},
            )
        return response

    def update(self, request, *args, **kwargs):
        target_user = self.get_object()
        if target_user.is_super_admin and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can modify a Super Administrator account."},
                status=status.HTTP_403_FORBIDDEN
            )
        if request.data.get("role") == "super_admin" and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can assign the Super Administrator role."},
                status=status.HTTP_403_FORBIDDEN
            )
        before_state = {"role": target_user.role, "email": target_user.email, "is_active": target_user.is_active}
        response = super().update(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            AuditService.log_event(
                action="USER_UPDATED",
                category=AuditLog.Category.USER_MANAGEMENT,
                actor=request.user,
                request=request,
                status=AuditLog.Status.SUCCESS,
                target_type="User",
                target_id=str(target_user.id),
                target_repr=f"{target_user.full_name} ({target_user.email})",
                description=f"Updated user account '{target_user.email}'.",
                changes={"before": before_state, "after": response.data},
            )
        return response

    def partial_update(self, request, *args, **kwargs):
        target_user = self.get_object()
        if target_user.is_super_admin and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can modify a Super Administrator account."},
                status=status.HTTP_403_FORBIDDEN
            )
        if request.data.get("role") == "super_admin" and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can assign the Super Administrator role."},
                status=status.HTTP_403_FORBIDDEN
            )
        before_state = {"role": target_user.role, "email": target_user.email, "is_active": target_user.is_active}
        response = super().partial_update(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            AuditService.log_event(
                action="USER_UPDATED",
                category=AuditLog.Category.USER_MANAGEMENT,
                actor=request.user,
                request=request,
                status=AuditLog.Status.SUCCESS,
                target_type="User",
                target_id=str(target_user.id),
                target_repr=f"{target_user.full_name} ({target_user.email})",
                description=f"Partially updated user account '{target_user.email}'.",
                changes={"before": before_state, "after": response.data},
            )
        return response

    @action(detail=True, methods=["post"], url_path="toggle-status")
    def toggle_status(self, request, pk=None):
        target_user = self.get_object()
        if target_user.is_super_admin and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can alter account status for a Super Administrator."},
                status=status.HTTP_403_FORBIDDEN
            )
        if target_user == request.user and target_user.is_super_admin:
            return Response(
                {"detail": "Security violation: Super Administrators cannot suspend their own active credentials."},
                status=status.HTTP_400_BAD_REQUEST
            )
        target_user.is_active = not target_user.is_active
        target_user.save(update_fields=["is_active"])
        new_status = "active" if target_user.is_active else "suspended"
        AuditService.log_event(
            action="USER_STATUS_TOGGLED",
            category=AuditLog.Category.USER_MANAGEMENT,
            actor=request.user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(target_user.id),
            target_repr=f"{target_user.full_name} ({target_user.email})",
            description=f"Changed account status for '{target_user.email}' to {new_status}.",
            changes={"is_active": target_user.is_active},
        )
        return Response({
            "status": "success",
            "is_active": target_user.is_active,
            "user": UserSerializer(target_user, context={"request": request}).data,
        })

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        target_user = self.get_object()
        if target_user.is_super_admin and not getattr(request.user, "is_super_admin", False):
            return Response(
                {"detail": "Permission denied: Only Super Administrators can reset credentials for a Super Administrator."},
                status=status.HTTP_403_FORBIDDEN
            )
        new_password = request.data.get("new_password") or "TempPass123!"
        target_user.set_password(new_password)
        target_user.save(update_fields=["password"])
        AuditService.log_event(
            action="USER_PASSWORD_RESET",
            category=AuditLog.Category.SECURITY,
            actor=request.user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(target_user.id),
            target_repr=f"{target_user.full_name} ({target_user.email})",
            description=f"Administrative password reset performed for '{target_user.email}' by {request.user.email}.",
        )
        return Response({"status": "success", "detail": f"Password reset successfully for {target_user.email}."})

    @action(detail=True, methods=["post"], url_path="resend-credentials")
    def resend_credentials(self, request, pk=None):
        """Admin action to resend welcome SMS and Email credentials to a student."""
        target_user = self.get_object()
        raw_password = target_user.serial_number or "Check with Admissions"
        from apps.notifications.tasks import dispatch_welcome_notifications
        result = dispatch_welcome_notifications(user_id=str(target_user.id), raw_password=raw_password)
        return Response({
            "status": "success",
            "message": f"Welcome credentials dispatched via SMS and Email to {target_user.email} ({target_user.phone or 'No phone'}).",
            "result": result
        })


    @action(detail=True, methods=["post"], url_path="avatar")
    def upload_avatar(self, request, pk=None):
        target_user = self.get_object()
        avatar_file = request.FILES.get("avatar") or request.FILES.get("file")
        if not avatar_file:
            return Response({"error": "no_file", "detail": "No image file provided."}, status=status.HTTP_400_BAD_REQUEST)
        if avatar_file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            return Response({"error": "invalid_type", "detail": "Only JPEG, PNG, WEBP, and GIF images are allowed."}, status=status.HTTP_400_BAD_REQUEST)
        if avatar_file.size > 5 * 1024 * 1024:
            return Response({"error": "file_too_large", "detail": "Avatar image size must be under 5 MB."}, status=status.HTTP_400_BAD_REQUEST)

        cloudinary_url = None
        try:
            import os
            import cloudinary
            import cloudinary.uploader
            from django.conf import settings

            storage_cfg = getattr(settings, "CLOUDINARY_STORAGE", {})
            cloud_name = storage_cfg.get("CLOUD_NAME") or os.environ.get("CLOUDINARY_CLOUD_NAME")
            api_key = storage_cfg.get("API_KEY") or os.environ.get("CLOUDINARY_API_KEY")
            api_secret = storage_cfg.get("API_SECRET") or os.environ.get("CLOUDINARY_API_SECRET")

            if cloud_name:
                if api_key and api_secret:
                    cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True)
                upload_result = cloudinary.uploader.upload(
                    avatar_file,
                    folder=getattr(settings, "CLOUDINARY_PROFILE_FOLDER", "uniportal-profile picture"),
                    public_id=f"user_{target_user.id}_avatar",
                    overwrite=True,
                    resource_type="image",
                )
                cloudinary_url = upload_result.get("secure_url") or upload_result.get("url")
        except Exception as e:
            logger.warning("Admin Cloudinary upload failed: %s", e)

        if cloudinary_url:
            target_user.avatar = cloudinary_url
            target_user.save(update_fields=["avatar"])
        else:
            target_user.avatar = avatar_file
            target_user.save(update_fields=["avatar"])

        return Response(UserSerializer(target_user, context={"request": request}).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="promote")
    def promote(self, request, pk=None):
        target_user = self.get_object()
        serializer = PromoteStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.users.services.progression_service import promote_student
        try:
            result = promote_student(
                student=target_user,
                target_level=serializer.validated_data.get("target_level"),
                academic_year=serializer.validated_data.get("academic_year", ""),
                semester=serializer.validated_data.get("semester", ""),
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            result["user"] = UserSerializer(target_user, context={"request": request}).data
            return Response(result, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="demote")
    def demote(self, request, pk=None):
        target_user = self.get_object()
        serializer = DemoteStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.users.services.progression_service import demote_student
        try:
            result = demote_student(
                student=target_user,
                target_level=serializer.validated_data.get("target_level"),
                reason=serializer.validated_data["reason"],
                academic_year=serializer.validated_data.get("academic_year", ""),
                semester=serializer.validated_data.get("semester", ""),
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            result["user"] = UserSerializer(target_user, context={"request": request}).data
            return Response(result, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="withdraw")
    def withdraw(self, request, pk=None):
        target_user = self.get_object()
        serializer = WithdrawStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.users.services.progression_service import withdraw_student
        try:
            result = withdraw_student(
                student=target_user,
                reason=serializer.validated_data["reason"],
                effective_date=serializer.validated_data.get("effective_date"),
                academic_year=serializer.validated_data.get("academic_year", ""),
                semester=serializer.validated_data.get("semester", ""),
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            result["user"] = UserSerializer(target_user, context={"request": request}).data
            return Response(result, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="reinstate")
    def reinstate(self, request, pk=None):
        target_user = self.get_object()
        serializer = ReinstateStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.users.services.progression_service import reinstate_student
        try:
            result = reinstate_student(
                student=target_user,
                target_level=serializer.validated_data.get("target_level"),
                academic_year=serializer.validated_data.get("academic_year", ""),
                semester=serializer.validated_data.get("semester", ""),
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            result["user"] = UserSerializer(target_user, context={"request": request}).data
            return Response(result, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="soft-delete")
    def soft_delete(self, request, pk=None):
        target_user = self.get_object()
        reason = request.data.get("reason", "")
        from apps.users.services.progression_service import soft_delete_student
        result = soft_delete_student(target_user, reason=reason, actor=request.user)
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        target_user = self.get_object()
        from apps.users.services.progression_service import restore_student
        result = restore_student(target_user, actor=request.user)
        result["user"] = UserSerializer(target_user, context={"request": request}).data
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=True, methods=["delete", "post"], url_path="permanent-delete")
    def permanent_delete(self, request, pk=None):
        if not getattr(request.user, "is_super_admin", False) and getattr(request.user, "role", "") not in ("admin", "super_admin"):
            return Response(
                {"detail": "Permission denied: Only System Administrators can permanently purge student records."},
                status=status.HTTP_403_FORBIDDEN
            )

        target_user = self.get_object()
        serializer = HardDeleteStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        force = serializer.validated_data.get("force", False)

        from apps.users.services.progression_service import hard_delete_student
        try:
            result = hard_delete_student(target_user, force=force, actor=request.user)
            return Response(result, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"], url_path="deletion-precheck")
    def deletion_precheck(self, request, pk=None):
        target_user = self.get_object()
        from apps.users.services.progression_service import can_hard_delete_student
        can_delete, blockers = can_hard_delete_student(target_user)
        return Response({
            "can_hard_delete": can_delete,
            "blockers": blockers,
            "student_id": target_user.student_id,
            "name": target_user.full_name,
        })

    @action(detail=False, methods=["post"], url_path="bulk-promote")
    def bulk_promote(self, request):
        serializer = BulkPromoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.users.services.progression_service import bulk_promote_cohort
        try:
            result = bulk_promote_cohort(
                student_ids=[str(i) for i in serializer.validated_data["student_ids"]],
                target_level=serializer.validated_data.get("target_level"),
                academic_year=serializer.validated_data.get("academic_year", ""),
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user,
            )
            return Response(result, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            msg = e.message if hasattr(e, "message") else str(e)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["get"], url_path="progression-history")
    def progression_history(self, request, pk=None):
        target_user = self.get_object()
        logs = target_user.progression_logs.all().order_by("-created_at")
        return Response(AcademicProgressionLogSerializer(logs, many=True).data)

    @action(detail=False, methods=["get"], url_path="roles-and-functions")
    def roles_and_functions(self, request):
        """
        Returns the catalog of institutional portal roles with default functions,
        and all granular functional capabilities.
        Non-superadmins receive only assignable subordinate roles.
        """
        from .constants import PORTAL_ROLES, PORTAL_FUNCTIONS
        roles = PORTAL_ROLES
        if not (request.user and getattr(request.user, "is_super_admin", False)):
            roles = [r for r in PORTAL_ROLES if r["code"] != "super_admin"]
        return Response({
            "roles": roles,
            "functions": PORTAL_FUNCTIONS,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="assign-role-and-functions")
    def assign_role_and_functions(self, request, pk=None):
        """
        Assigns or updates an institutional role and granular capabilities for a user.
        Authorized for Super Admin or users with 'users.manage_roles' capability.
        """
        if not (request.user.is_super_admin or request.user.has_portal_permission("users.manage_roles")):
            return Response(
                {"detail": "Permission denied: Requires role management authority."},
                status=status.HTTP_403_FORBIDDEN
            )

        target_user = self.get_object()
        serializer = AssignRoleAndFunctionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_role = serializer.validated_data.get("role")
        assigned_functions = serializer.validated_data.get("assigned_functions", [])

        # Shield super_admin accounts: only Super Admin can alter a super admin
        if target_user.is_super_admin and not request.user.is_super_admin:
            return Response(
                {"detail": "Permission denied: Only Super Administrators can modify a Super Administrator's role or capabilities."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Prevent privilege escalation: non-superadmin cannot assign super_admin role
        if new_role == "super_admin" and not request.user.is_super_admin:
            return Response(
                {"detail": "Permission denied: Only Super Administrators can grant the Super Administrator role."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Prevent non-superadmin from granting users.manage_roles
        if "users.manage_roles" in assigned_functions and not request.user.is_super_admin:
            return Response(
                {"detail": "Permission denied: Only Super Administrators can grant role management capabilities."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Prevent super admin from demoting themselves
        if target_user == request.user and target_user.is_super_admin and new_role and new_role != "super_admin":
            return Response(
                {"detail": "Security violation: Super Administrators cannot revoke their own Super Administrator role."},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_role = target_user.role
        if new_role:
            target_user.role = new_role
            if new_role in ("super_admin", "admin", "academic_officer", "staff"):
                target_user.is_staff = True
            elif new_role in ("student", "lecturer", "finance"):
                if not target_user.is_superuser:
                    target_user.is_staff = False

        target_user.assigned_functions = assigned_functions
        target_user.save(update_fields=["role", "assigned_functions", "is_staff"])

        from .models import AcademicProgressionLog
        AcademicProgressionLog.objects.create(
            student=target_user,
            action=AcademicProgressionLog.ActionType.STATUS_CHANGE,
            from_status=f"Role:{old_role}",
            to_status=f"Role:{target_user.role}",
            reason=f"Role & permissions updated by {request.user.email}",
            performed_by=request.user,
            metadata={
                "assigned_functions": assigned_functions,
                "effective_functions": target_user.effective_functions,
            }
        )

        AuditService.log_event(
            action="USER_ROLE_ASSIGNED",
            category=AuditLog.Category.USER_MANAGEMENT,
            actor=request.user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(target_user.id),
            target_repr=f"{target_user.full_name} ({target_user.email})",
            description=f"Assigned role '{target_user.role}' with {len(assigned_functions)} capabilities to '{target_user.email}'.",
            changes={
                "before": {"role": old_role},
                "after": {"role": target_user.role, "assigned_functions": assigned_functions},
            },
            metadata={"assigned_functions": assigned_functions},
        )

        return Response({
            "status": "success",
            "message": f"Successfully updated role and capabilities for {target_user.full_name or target_user.email}.",
            "user": UserSerializer(target_user, context={"request": request}).data,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="export-students")
    def export_students(self, request):
        """Export student directory in CSV format for Academic Officers and Admins."""
        import csv
        from django.http import HttpResponse
        from django.utils import timezone
        from apps.grades.gpa import compute_cumulative_gpa

        role = request.query_params.get("role")
        user_type = request.query_params.get("user_type")
        department = request.query_params.get("department")

        qs = User.objects.all().order_by("last_name", "first_name")
        if not (request.user and getattr(request.user, "is_super_admin", False)):
            qs = qs.exclude(role="super_admin").exclude(is_superuser=True)

        if user_type == "student":
            qs = qs.filter(role="student")
        elif user_type in ("staff", "faculty"):
            qs = qs.exclude(role="student")
        elif role and role != "all":
            qs = qs.filter(role=role)

        if department:
            from django.db.models import Q
            qs = qs.filter(Q(department__icontains=department) | Q(profile__major__icontains=department))

        search = request.query_params.get("search")
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(student_id__icontains=search) |
                Q(department__icontains=search)
            )

        timestamp_str = timezone.now().strftime("%Y%m%d_%H%M")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        if user_type == "student":
            filename_prefix = "student_directory"
        elif user_type in ("staff", "faculty"):
            filename_prefix = "faculty_directory"
        else:
            filename_prefix = "users_directory"
        response["Content-Disposition"] = f'attachment; filename="asdam_{filename_prefix}_{timestamp_str}.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow(["INSTITUTIONAL STUDENT DIRECTORY & DEMOGRAPHICS"])
        writer.writerow(["Exported At", timezone.now().strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Filter Role", role or "All"])
        writer.writerow([])
        writer.writerow([
            "Student ID / Index No",
            "First Name",
            "Last Name",
            "Full Name",
            "Email Address",
            "Department / Major",
            "Academic Level",
            "Enrollment Year",
            "Cumulative GPA",
            "Credits Earned",
            "Account Status",
            "Registration Date",
        ])

        from apps.grades.models import Transcript

        for u in qs:
            gpa = 0.0
            total_credits = 0
            if u.role == "student":
                latest_rec = u.semester_records.order_by("-computed_at").first()
                if latest_rec and latest_rec.cumulative_gpa is not None:
                    gpa = float(latest_rec.cumulative_gpa)
                    total_credits = latest_rec.cumulative_credits_earned
                else:
                    gpa_val = compute_cumulative_gpa(u)
                    if isinstance(gpa_val, dict):
                        gpa = float(gpa_val.get("gpa", 0.0) or 0.0)
                        total_credits = int(gpa_val.get("total_credits", 0) or 0)
                    elif gpa_val is not None:
                        gpa = float(gpa_val)

                    if not total_credits:
                        total_credits = sum(
                            t.credits_earned for t in Transcript.objects.filter(student=u, grade_points__isnull=False)
                        )

            profile = getattr(u, "profile", None)
            level = getattr(profile, "academic_level", "") if profile else ""
            enroll_year = getattr(profile, "enrollment_year", "") if profile else ""

            writer.writerow([
                u.student_id or f"STU-{str(u.id)[:6].upper()}",
                u.first_name,
                u.last_name,
                u.full_name or f"{u.first_name} {u.last_name}",
                u.email,
                u.department or getattr(profile, "major", "Undeclared"),
                f"Level {level}" if level else "N/A",
                enroll_year or "N/A",
                f"{gpa:.2f}",
                total_credits,
                "Active" if u.is_active else "Suspended / Inactive",
                u.created_at.strftime("%Y-%m-%d") if u.created_at else "",
            ])

        AuditService.log_event(
            action="ROSTER_EXPORTED",
            category=AuditLog.Category.USER_MANAGEMENT,
            actor=request.user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="StudentRoster",
            target_repr=f"Export ({qs.count()} records)",
            description=f"Exported {qs.count()} user records to CSV.",
            metadata={"count": qs.count(), "user_type": user_type, "role": role},
        )
        return response


class SystemStatsView(APIView):
    """Admin dashboard stats."""
    permission_classes = [IsAdminOrStaff]

    def get(self, request):
        from apps.courses.models import Course
        from apps.grades.models import GradeBatch
        students = User.objects.filter(role="student").count()
        instructors = User.objects.filter(role="instructor").count()
        courses = Course.objects.count()
        pending_batches = GradeBatch.objects.filter(status="pending_review").count()
        
        return Response({
            "total_students": students,
            "total_instructors": instructors,
            "total_courses": courses,
            "pending_batches": pending_batches,
        })


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Super-Admin and Auditor API for inspecting immutable activity and security audit logs.
    Supports granular filtering, search, metrics calculation, and CSV compliance export.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        user = self.request.user
        is_super = getattr(user, "is_super_admin", False) or getattr(user, "is_superuser", False)
        has_perm = is_super or "audit.view_logs" in getattr(user, "effective_functions", [])
        if not has_perm:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Access restricted: You do not have permission to inspect system audit logs.")

        qs = AuditLog.objects.select_related("actor").all().order_by("-timestamp")

        category = self.request.query_params.get("category")
        if category and category != "all":
            qs = qs.filter(action_category=category)

        status_val = self.request.query_params.get("status")
        if status_val and status_val != "all":
            qs = qs.filter(status=status_val)

        action_val = self.request.query_params.get("action")
        if action_val:
            qs = qs.filter(action=action_val)

        actor_id = self.request.query_params.get("actor")
        if actor_id:
            qs = qs.filter(actor_id=actor_id)

        start_date = self.request.query_params.get("start_date")
        if start_date:
            qs = qs.filter(timestamp__gte=start_date)

        end_date = self.request.query_params.get("end_date")
        if end_date:
            qs = qs.filter(timestamp__lte=end_date)

        search = self.request.query_params.get("search")
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(actor_email__icontains=search) |
                Q(target_repr__icontains=search) |
                Q(description__icontains=search) |
                Q(ip_address__icontains=search) |
                Q(action__icontains=search)
            )

        return qs

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """Executive KPI metrics on system audit events and security posture."""
        user = request.user
        is_super = getattr(user, "is_super_admin", False) or getattr(user, "is_superuser", False)
        has_perm = is_super or "audit.view_logs" in getattr(user, "effective_functions", [])
        if not has_perm:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Access restricted.")

        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count

        now = timezone.now()
        yesterday = now - timedelta(hours=24)
        week_ago = now - timedelta(days=7)

        total_events = AuditLog.objects.count()
        failed_logins_24h = AuditLog.objects.filter(
            action__in=["AUTH_LOGIN_FAILED", "AUTH_LOGIN_BLOCKED"],
            timestamp__gte=yesterday
        ).count()
        admin_actions_7d = AuditLog.objects.filter(
            action_category__in=[AuditLog.Category.USER_MANAGEMENT, AuditLog.Category.SECURITY],
            timestamp__gte=week_ago
        ).count()
        security_alerts = AuditLog.objects.filter(
            status__in=[AuditLog.Status.FAILURE, AuditLog.Status.WARNING],
            timestamp__gte=week_ago
        ).count()

        category_counts = dict(
            AuditLog.objects.values("action_category")
            .annotate(count=Count("id"))
            .values_list("action_category", "count")
        )

        recent_actors = list(
            AuditLog.objects.exclude(actor_email="Anonymous")
            .values("actor_email", "actor_role")
            .annotate(event_count=Count("id"))
            .order_by("-event_count")[:5]
        )

        return Response({
            "total_events": total_events,
            "failed_logins_24h": failed_logins_24h,
            "admin_actions_7d": admin_actions_7d,
            "security_alerts_7d": security_alerts,
            "category_counts": category_counts,
            "recent_actors": recent_actors,
        })

    @action(detail=False, methods=["get"], url_path="export-csv")
    def export_csv(self, request):
        """Stream formal CSV export of audit logs for external audit & compliance."""
        import csv
        from django.http import HttpResponse
        from django.utils import timezone

        qs = self.get_queryset()[:2000]
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        timestamp_str = timezone.now().strftime("%Y%m%d_%H%M%S")
        response["Content-Disposition"] = f'attachment; filename="system_audit_logs_{timestamp_str}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Timestamp (UTC)",
            "Category",
            "Action",
            "Status",
            "Actor Email",
            "Actor Role",
            "Target Type",
            "Target ID",
            "Target Identifier / Repr",
            "Description",
            "IP Address",
            "User Agent",
        ])

        for log in qs:
            writer.writerow([
                log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                log.get_action_category_display(),
                log.action,
                log.status.upper(),
                log.actor_email,
                log.actor_role,
                log.target_type,
                log.target_id,
                log.target_repr,
                log.description,
                log.ip_address or "",
                log.user_agent or "",
            ])

        AuditService.log_event(
            action="AUDIT_LOGS_EXPORTED",
            category=AuditLog.Category.SECURITY,
            actor=request.user,
            request=request,
            status=AuditLog.Status.SUCCESS,
            target_type="AuditLog",
            target_repr=f"Exported {qs.count()} audit records",
            description=f"Auditor '{request.user.email}' exported {qs.count()} audit trail records to CSV.",
        )
        return response
