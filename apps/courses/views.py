"""
Course ViewSets — complete production version.
Covers: catalog, my-courses, registration, bulk-register, drop, schedule conflict check.
"""
import logging
from django.db.models import Count, Q, Prefetch
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from .models import Course, Lesson, Enrollment, Category, RegistrationWindow
from .serializers import (
    CourseListSerializer, CourseDetailSerializer,
    EnrollmentSerializer, CategorySerializer,
    BulkRegistrationSerializer, RegistrationWindowSerializer,
    DropEnrollmentSerializer,
)
from .registration import RegistrationService, RegistrationError
from core.permissions import IsInstructor, IsAdminOrReadOnly, IsAdminOrStaff
from core.pagination import StandardResultsPagination, CursorPagination

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_enrollment_context(user):
    """Build O(1) lookup dicts for is_enrolled / enrollment_status."""
    if not user.is_authenticated:
        return {"enrolled_ids": set(), "enrollment_status_map": {}}
    rows = (
        Enrollment.objects
        .filter(student=user)
        .values_list("course_id", "status")
    )
    enrolled_ids = set()
    status_map = {}
    for course_id, st in rows:
        key = str(course_id)
        status_map[key] = st
        if st in (Enrollment.Status.ACTIVE, Enrollment.Status.WAITLISTED):
            enrolled_ids.add(key)
    return {"enrolled_ids": enrolled_ids, "enrollment_status_map": status_map}


# ── Category ──────────────────────────────────────────────────────────────────

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]

    @method_decorator(cache_page(60 * 60))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


# ── Course ────────────────────────────────────────────────────────────────────

class CourseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "category", "credits", "semester"]
    search_fields = ["title", "code", "description", "tags"]
    ordering_fields = ["title", "created_at", "credits", "start_date"]
    ordering = ["-created_at"]
    pagination_class = StandardResultsPagination

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdminOrStaff()]
        return super().get_permissions()

    def get_queryset(self):
        qs = (
            Course.objects
            .select_related("category")
            .prefetch_related(
                Prefetch("instructors"),
                Prefetch("schedules"),
                Prefetch("prerequisites"),
                Prefetch(
                    "lessons",
                    queryset=Lesson.objects.filter(published_at__isnull=False).order_by("order"),
                ),
            )
        )
        user = self.request.user
        if user.role == "student":
            qs = qs.filter(status=Course.Status.ACTIVE)
        elif user.role == "instructor":
            qs = qs.filter(Q(status=Course.Status.ACTIVE) | Q(instructors=user)).distinct()
        return qs

    def get_serializer_class(self):
        if self.action in ("retrieve", "create", "update", "partial_update"):
            return CourseDetailSerializer
        return CourseListSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx.update(_build_enrollment_context(self.request.user))
        return ctx

    # ── Catalog (cached for anonymous/students) ───────────────────────────
    def list(self, request, *args, **kwargs):
        if request.user.role == "student":
            cache_key = f"course_list:{request.GET.urlencode()}"
            cached = cache.get(cache_key)
            if cached:
                return Response(cached)
            response = super().list(request, *args, **kwargs)
            cache.set(cache_key, response.data, 60 * 3)
            return response
        return super().list(request, *args, **kwargs)

    # ── My courses ────────────────────────────────────────────────────────
    @action(detail=False, methods=["get"], url_path="my-courses")
    def my_courses(self, request):
        if request.user.role == "instructor":
            courses = (
                Course.objects
                .filter(instructors=request.user)
                .select_related("category")
                .prefetch_related("schedules", "instructors")
                .order_by("-created_at")
            )
        else:
            enrollments = (
                Enrollment.objects
                .filter(student=request.user, status__in=[
                    Enrollment.Status.ACTIVE, Enrollment.Status.WAITLISTED
                ])
                .select_related(
                    "course__category",
                )
                .prefetch_related("course__schedules", "course__instructors")
                .order_by("-enrolled_at")
            )
            courses = [e.course for e in enrollments]
        ctx = self.get_serializer_context()
        serializer = CourseListSerializer(courses, many=True, context=ctx)
        return Response(serializer.data)

    # ── Single-course register ────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="register")
    def register(self, request, pk=None):
        course = self.get_object()
        serializer = EnrollmentSerializer(
            data={"course_id": str(course.id)},
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        enrollment = serializer.save()
        logger.info("Registered: student=%s course=%s status=%s", request.user.id, course.code, enrollment.status)
        return Response(EnrollmentSerializer(enrollment, context=self.get_serializer_context()).data,
                        status=status.HTTP_201_CREATED)

    # ── Bulk registration ─────────────────────────────────────────────────
    @action(detail=False, methods=["post"], url_path="bulk-register")
    def bulk_register(self, request):
        serializer = BulkRegistrationSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        results = serializer.save()
        registered = EnrollmentSerializer(
            results["registered"], many=True, context=self.get_serializer_context()
        ).data
        return Response({
            "registered": registered,
            "errors": results["errors"],
            "summary": {
                "registered_count": len(results["registered"]),
                "error_count": len(results["errors"]),
                "total_credits": sum(e.course.credits for e in results["registered"]),
            }
        }, status=status.HTTP_201_CREATED if registered else status.HTTP_207_MULTI_STATUS)

    # ── Registration window status ────────────────────────────────────────
    @action(detail=False, methods=["get"], url_path="registration-window", permission_classes=[IsAuthenticated])
    def registration_window(self, request):
        semester = request.query_params.get("semester", "")
        qs = RegistrationWindow.objects.filter(is_active=True)
        if semester:
            qs = qs.filter(semester=semester)
        window = qs.order_by("-opens_at").first()
        if not window:
            return Response({"is_open": False, "detail": "No active registration window found."})
        return Response(RegistrationWindowSerializer(window).data)

    # ── Conflict check (before registering) ───────────────────────────────
    @action(detail=True, methods=["get"], url_path="check-conflict")
    def check_conflict(self, request, pk=None):
        course = self.get_object()
        enrolled_ids = list(
            Enrollment.objects.filter(
                student=request.user,
                status=Enrollment.Status.ACTIVE,
            ).values_list("course_id", flat=True)
        )
        from .models import CourseSchedule
        my_schedules = CourseSchedule.objects.filter(course_id__in=enrolled_ids)
        new_schedules = CourseSchedule.objects.filter(course=course)
        conflicts = []
        for ns in new_schedules:
            for ms in my_schedules.filter(day_of_week=ns.day_of_week):
                if ms.start_time < ns.end_time and ns.start_time < ms.end_time:
                    conflicts.append({
                        "day": ns.get_day_of_week_display(),
                        "new_slot": f"{ns.start_time}–{ns.end_time}",
                        "conflict_with": ms.course.code,
                        "existing_slot": f"{ms.start_time}–{ms.end_time}",
                    })
        return Response({"has_conflict": bool(conflicts), "conflicts": conflicts})


# ── Enrollment ────────────────────────────────────────────────────────────────

class EnrollmentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = EnrollmentSerializer
    pagination_class = StandardResultsPagination

    def get_queryset(self):
        return (
            Enrollment.objects
            .filter(student=self.request.user)
            .select_related("course__category")
            .prefetch_related("course__schedules", "course__instructors")
            .order_by("-enrolled_at")
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx.update(_build_enrollment_context(self.request.user))
        return ctx

    @action(detail=True, methods=["post"], url_path="drop")
    def drop(self, request, pk=None):
        enrollment = self.get_object()
        serializer = DropEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        semester = enrollment.course.semester or ""
        service = RegistrationService(request.user, semester)
        try:
            updated = service.drop(enrollment)
        except RegistrationError as e:
            return Response({"error": e.code, "detail": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        logger.info("Dropped: student=%s course=%s", request.user.id, enrollment.course.code)
        return Response({"status": "dropped", "enrollment_id": str(updated.id)})

    @action(detail=False, methods=["get"], url_path="history")
    def history(self, request):
        """All enrollments including dropped/completed."""
        qs = (
            Enrollment.objects
            .filter(student=request.user)
            .select_related("course__category")
            .order_by("-enrolled_at")
        )
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)
