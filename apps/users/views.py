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
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    RegisterSerializer, UserSerializer, ChangePasswordSerializer,
    MOHVerifySerializer, MOHRegisterSerializer, MultiIdentifierTokenObtainPairSerializer,
    StudentRegistrationCompletionSerializer
)
from .services.roster_service import process_roster_csv, generate_sample_csv_template
from core.permissions import IsAdminOrStaff

logger = logging.getLogger(__name__)
User = get_user_model()


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

    def get_queryset(self):
        qs = User.objects.all().order_by("-created_at")
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
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

    @action(detail=False, methods=["post"], url_path="upload-moh-roster")
    def upload_moh_roster(self, request):
        """
        Upload student roster with MOH PIN and Serial Number.
        Generates ASDAM Student IDs for Nursing and Midwifery students.
        """
        csv_file = request.FILES.get("file") or request.FILES.get("csv_file")
        if not csv_file:
            return Response(
                {"detail": "No CSV file uploaded. Please select a valid student roster file."},
                status=status.HTTP_400_BAD_REQUEST
            )

        default_program = request.data.get("default_program")
        default_class = request.data.get("default_class") or "100"
        default_year = request.data.get("default_year")
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
            resp_status = status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST
            return Response(result, status=resp_status)
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

    @action(detail=True, methods=["post"], url_path="toggle-status")
    def toggle_status(self, request, pk=None):
        target_user = self.get_object()
        target_user.is_active = not target_user.is_active
        target_user.save(update_fields=["is_active"])
        return Response({
            "status": "success",
            "is_active": target_user.is_active,
            "user": UserSerializer(target_user, context={"request": request}).data,
        })

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        target_user = self.get_object()
        new_password = request.data.get("new_password") or "TempPass123!"
        target_user.set_password(new_password)
        target_user.save(update_fields=["password"])
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

    @action(detail=False, methods=["get"], url_path="export-students")
    def export_students(self, request):
        """Export student directory in CSV format for Academic Officers and Admins."""
        import csv
        from django.http import HttpResponse
        from django.utils import timezone
        from apps.grades.gpa import compute_cumulative_gpa

        role = request.query_params.get("role", "student")
        qs = User.objects.all().order_by("last_name", "first_name")
        if role and role != "all":
            qs = qs.filter(role=role)

        search = request.query_params.get("search")
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(email__icontains=search) |
                Q(student_id__icontains=search)
            )

        timestamp_str = timezone.now().strftime("%Y%m%d_%H%M")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename_prefix = f"{role}_directory" if role and role != "all" else "user_directory"
        if not role or role == "student":
            filename_prefix = "student_directory"
        response["Content-Disposition"] = f'attachment; filename="{filename_prefix}_{timestamp_str}.csv"'
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
