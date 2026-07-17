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

from .serializers import RegisterSerializer, UserSerializer, ChangePasswordSerializer
from core.permissions import IsAdminOrStaff

logger = logging.getLogger(__name__)
User = get_user_model()


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


class UserViewSet(viewsets.ModelViewSet):
    """Admin endpoint to manage users."""
    permission_classes = [IsAdminOrStaff]
    def get_queryset(self):
        qs = User.objects.all().order_by("-created_at")
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        return qs

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            from .serializers import AdminCreateUserSerializer
            return AdminCreateUserSerializer
        return UserSerializer


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
