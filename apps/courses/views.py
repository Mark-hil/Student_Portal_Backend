"""
Course ViewSets — complete production version.
Covers: catalog, my-courses, registration, bulk-register, drop, schedule conflict check.
"""
import logging
from django.db.models import Count, Q, Prefetch
from django.core.cache import cache
from django.utils import timezone
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
    DropEnrollmentSerializer, LessonSerializer,
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
        if getattr(user, "is_student_role", False) or user.role == "student":
            qs = qs.filter(status=Course.Status.ACTIVE)
        elif getattr(user, "is_instructor_role", False) or user.role in ("instructor", "lecturer"):
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
        if getattr(request.user, "is_student_role", False) or request.user.role == "student":
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
        if getattr(request.user, "is_instructor_role", False) or request.user.role in ("instructor", "lecturer"):
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
            return Response({"is_open": False, "status_label": "closed", "detail": "No active registration window found."})
        return Response(RegistrationWindowSerializer(window).data)

    # ── Manage Registration Window (Admin/Staff) ───────────────────────────
    @action(detail=False, methods=["post", "patch"], url_path="registration-window/manage", permission_classes=[IsAuthenticated])
    def manage_registration_window(self, request):
        if not (getattr(request.user, "is_academic_officer", False) or getattr(request.user, "is_super_admin", False) or request.user.is_staff or request.user.role in ("admin", "staff", "academic_officer", "super_admin")):
            return Response({"detail": "Only academic staff and administrators can manage registration windows."}, status=status.HTTP_403_FORBIDDEN)
        
        semester = request.data.get("semester") or "Spring 2025"
        extend_days = request.data.get("extend_days")
        reopen_flag = request.data.get("reopen")
        opens_at_str = request.data.get("opens_at")
        closes_at_str = request.data.get("closes_at")
        is_active = request.data.get("is_active")

        window = RegistrationWindow.objects.filter(semester=semester).first()
        if not window:
            now = timezone.now()
            from datetime import timedelta
            window = RegistrationWindow.objects.create(
                semester=semester,
                opens_at=now,
                closes_at=now + timedelta(days=14),
                is_active=True
            )

        if extend_days:
            try:
                window.extend(int(extend_days))
            except Exception as e:
                return Response({"detail": f"Failed to extend window: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        elif reopen_flag:
            window.reopen()
        
        if opens_at_str:
            window.opens_at = opens_at_str
        if closes_at_str:
            window.closes_at = closes_at_str
        if is_active is not None:
            window.is_active = bool(is_active)
        
        window.save()
        return Response(RegistrationWindowSerializer(window).data)

    # ── Registration Reports & CSV Exports ────────────────────────────────
    @action(detail=False, methods=["get"], url_path="reports/registration-stats", permission_classes=[IsAuthenticated])
    def registration_stats(self, request):
        if not (getattr(request.user, "is_academic_officer", False) or getattr(request.user, "is_super_admin", False) or request.user.is_staff or request.user.role in ("admin", "staff", "academic_officer", "super_admin")):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        semester = request.query_params.get("semester", "Spring 2025")
        students = User.objects.filter(role=User.Role.STUDENT, is_active=True)
        total_students = students.count()

        active_enrollments = Enrollment.objects.filter(
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.WAITLISTED]
        )
        if semester:
            active_enrollments = active_enrollments.filter(course__semester=semester)

        registered_student_ids = set(active_enrollments.values_list("student_id", flat=True))
        registered_count = len(registered_student_ids)
        unregistered_count = max(0, total_students - registered_count)
        rate_pct = round((registered_count / total_students * 100), 1) if total_students > 0 else 0

        total_credits = sum(e.course.credits for e in active_enrollments.select_related("course"))
        avg_credits = round(total_credits / registered_count, 1) if registered_count > 0 else 0

        return Response({
            "semester": semester,
            "total_students": total_students,
            "registered_students": registered_count,
            "unregistered_students": unregistered_count,
            "registration_rate_pct": rate_pct,
            "total_active_enrollments": active_enrollments.count(),
            "avg_credits_per_registered": avg_credits,
        })

    @action(detail=False, methods=["get"], url_path="reports/registered-csv", permission_classes=[IsAuthenticated])
    def registered_csv(self, request):
        if not (getattr(request.user, "is_academic_officer", False) or getattr(request.user, "is_super_admin", False) or request.user.is_staff or request.user.role in ("admin", "staff", "academic_officer", "super_admin")):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        import csv
        from django.http import HttpResponse
        from django.contrib.auth import get_user_model
        from collections import defaultdict

        User = get_user_model()
        semester = request.query_params.get("semester", "")

        enrollments = (
            Enrollment.objects
            .filter(status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.WAITLISTED])
            .select_related("student", "course")
        )
        if semester:
            enrollments = enrollments.filter(course__semester=semester)

        student_enrollments = defaultdict(list)
        for e in enrollments:
            student_enrollments[e.student].append(e)

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="registered_students_{semester or "all"}.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow([
            "Student ID", "First Name", "Last Name", "Email", "Department/Major",
            "Total Enrolled Courses", "Course Codes", "Total Registered Credits", "Registration Status"
        ])

        for student, enr_list in student_enrollments.items():
            courses_str = ", ".join(e.course.code for e in enr_list)
            total_credits = sum(e.course.credits for e in enr_list)
            writer.writerow([
                student.student_id or f"STU-{str(student.id)[:6].upper()}",
                student.first_name,
                student.last_name,
                student.email,
                student.department or getattr(getattr(student, 'profile', None), 'major', 'Undeclared'),
                len(enr_list),
                courses_str,
                total_credits,
                "Registered (Full-time)" if total_credits >= 12 else "Registered (Part-time)"
            ])

        return response

    @action(detail=False, methods=["get"], url_path="reports/unregistered-csv", permission_classes=[IsAuthenticated])
    def unregistered_csv(self, request):
        if not (getattr(request.user, "is_academic_officer", False) or getattr(request.user, "is_super_admin", False) or request.user.is_staff or request.user.role in ("admin", "staff", "academic_officer", "super_admin")):
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        import csv
        from django.http import HttpResponse
        from django.contrib.auth import get_user_model

        User = get_user_model()
        semester = request.query_params.get("semester", "")

        active_enrollments = Enrollment.objects.filter(
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.WAITLISTED]
        )
        if semester:
            active_enrollments = active_enrollments.filter(course__semester=semester)

        registered_student_ids = set(active_enrollments.values_list("student_id", flat=True))
        unregistered_students = User.objects.filter(
            role=User.Role.STUDENT, is_active=True
        ).exclude(id__in=registered_student_ids).order_by("last_name", "first_name")

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="unregistered_students_{semester or "all"}.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow([
            "Student ID", "First Name", "Last Name", "Email", "Phone",
            "Department/Major", "Registration Status", "Action Required"
        ])

        for student in unregistered_students:
            writer.writerow([
                student.student_id or f"STU-{str(student.id)[:6].upper()}",
                student.first_name,
                student.last_name,
                student.email,
                student.phone or "N/A",
                student.department or getattr(getattr(student, 'profile', None), 'major', 'Undeclared'),
                "Not Registered (0 Credits)",
                "Contact student / Academic Advisor follow-up"
            ])

        return response

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

    def perform_destroy(self, instance):
        """Soft-archive if active enrollments exist, otherwise delete."""
        if instance.enrollments.filter(status=Enrollment.Status.ACTIVE).exists():
            instance.status = Course.Status.ARCHIVED
            instance.save(update_fields=["status"])
        else:
            instance.delete()

    @action(detail=True, methods=["get"], url_path="roster")
    def roster(self, request, pk=None):
        """Instructor/admin class roster with enrollment details and running grades."""
        course = self.get_object()
        user = request.user
        if (getattr(user, "is_instructor_role", False) or user.role in ("instructor", "lecturer")) and not course.instructors.filter(pk=user.pk).exists():
            return Response({"error": "forbidden", "detail": "You do not instruct this course."}, status=status.HTTP_403_FORBIDDEN)
        if not (getattr(user, "is_instructor_role", False) or getattr(user, "is_academic_officer", False) or getattr(user, "is_super_admin", False) or user.is_staff or user.role in ("instructor", "lecturer", "staff", "admin", "academic_officer", "super_admin")):
            return Response({"error": "forbidden", "detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        from apps.grades.gpa import compute_course_final_grade
        enrollments = (
            course.enrollments
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )

        students_data = []
        for e in enrollments:
            s = e.student
            grade_info = compute_course_final_grade(s, course) if e.status == Enrollment.Status.ACTIVE else {"letter": "—", "percentage": 0.0}
            students_data.append({
                "enrollment_id": str(e.id),
                "student_id": str(s.id),
                "student_code": s.student_id or f"STU-{str(s.id)[:6].upper()}",
                "name": s.full_name,
                "email": s.email,
                "department": s.department or getattr(getattr(s, "profile", None), "major", "Undeclared"),
                "status": e.status,
                "enrolled_at": e.enrolled_at,
                "progress_pct": float(e.progress_pct),
                "current_grade": grade_info.get("letter", "—"),
                "current_pct": grade_info.get("percentage", 0.0),
            })

        return Response({
            "course_id": str(course.id),
            "course_code": course.code,
            "course_title": course.title,
            "total_enrolled": len(students_data),
            "active_count": sum(1 for x in students_data if x["status"] == "active"),
            "waitlisted_count": sum(1 for x in students_data if x["status"] == "waitlisted"),
            "dropped_count": sum(1 for x in students_data if x["status"] == "dropped"),
            "students": students_data,
        })

    @action(detail=True, methods=["get"], url_path="export-roster")
    def export_roster(self, request, pk=None):
        """Export class roster for instructor/staff in CSV format."""
        import csv
        from django.http import HttpResponse
        from apps.grades.gpa import compute_course_final_grade

        course = self.get_object()
        user = request.user
        if (getattr(user, "is_instructor_role", False) or user.role in ("instructor", "lecturer")) and not course.instructors.filter(pk=user.pk).exists():
            return Response({"error": "forbidden", "detail": "You do not instruct this course."}, status=status.HTTP_403_FORBIDDEN)
        if not (getattr(user, "is_instructor_role", False) or getattr(user, "is_academic_officer", False) or getattr(user, "is_super_admin", False) or user.is_staff or user.role in ("instructor", "lecturer", "staff", "admin", "academic_officer", "super_admin")):
            return Response({"error": "forbidden", "detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        timestamp_str = timezone.now().strftime("%Y%m%d_%H%M")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{course.code}_student_roster_{timestamp_str}.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow([f"COURSE ENROLLMENT ROSTER: {course.code} - {course.title}"])
        writer.writerow(["Semester", course.semester, "Credits", course.credits])
        writer.writerow(["Exported At", timezone.now().strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow([])
        writer.writerow([
            "Student ID / Index No",
            "Student Full Name",
            "Email Address",
            "Department / Major",
            "Enrollment Status",
            "Enrolled Date",
            "Progress (%)",
            "Current Average (%)",
            "Current Letter Grade",
        ])

        enrollments = (
            course.enrollments
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )

        for e in enrollments:
            s = e.student
            grade_info = compute_course_final_grade(s, course) if e.status == Enrollment.Status.ACTIVE else {}
            if not grade_info:
                grade_info = {"letter": "—", "percentage": None}
            pct = grade_info.get("percentage")
            pct_val = f"{float(pct):.1f}%" if pct is not None else "—"

            writer.writerow([
                s.student_id or f"STU-{str(s.id)[:6].upper()}",
                s.full_name or s.email,
                s.email,
                s.department or getattr(getattr(s, "profile", None), "major", "Undeclared"),
                e.get_status_display() if hasattr(e, "get_status_display") else str(e.status).capitalize(),
                e.enrolled_at.strftime("%Y-%m-%d") if e.enrolled_at else "N/A",
                f"{float(e.progress_pct):.1f}%",
                pct_val,
                grade_info.get("letter", "—") or "—",
            ])

        return response

    @action(detail=True, methods=["get"], url_path="export-grades")
    def export_grades(self, request, pk=None):
        """Export comprehensive grade sheet across assignments for the course."""
        import csv
        from django.http import HttpResponse
        from apps.grades.models import Submission
        from apps.grades.gpa import compute_course_final_grade

        course = self.get_object()
        user = request.user
        if (getattr(user, "is_instructor_role", False) or user.role in ("instructor", "lecturer")) and not course.instructors.filter(pk=user.pk).exists():
            return Response({"error": "forbidden", "detail": "You do not instruct this course."}, status=status.HTTP_403_FORBIDDEN)
        if not (getattr(user, "is_instructor_role", False) or getattr(user, "is_academic_officer", False) or getattr(user, "is_super_admin", False) or user.is_staff or user.role in ("instructor", "lecturer", "staff", "admin", "academic_officer", "super_admin")):
            return Response({"error": "forbidden", "detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        assignments = list(course.assignments.all().order_by("due_date", "created_at"))
        timestamp_str = timezone.now().strftime("%Y%m%d_%H%M")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{course.code}_grade_sheet_{timestamp_str}.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow([f"COURSE GRADE & ASSESSMENT REPORT: {course.code} - {course.title}"])
        writer.writerow(["Semester", course.semester, "Total Assessments", len(assignments)])
        writer.writerow(["Exported At", timezone.now().strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow([])

        # Header row with dynamic assignment columns
        header = ["Student ID / Index No", "Student Full Name", "Email"]
        for a in assignments:
            header.append(f"{a.title} (Max {a.max_score} | Weight {a.weight}%)")
        header.extend(["Final Course Average (%)", "Final Letter Grade"])
        writer.writerow(header)

        enrollments = (
            course.enrollments
            .filter(status=Enrollment.Status.ACTIVE)
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )

        for e in enrollments:
            s = e.student
            row = [
                s.student_id or f"STU-{str(s.id)[:6].upper()}",
                s.full_name or s.email,
                s.email,
            ]
            for a in assignments:
                sub = Submission.objects.filter(assignment=a, student=s).order_by("-updated_at").first()
                if sub and sub.score is not None:
                    row.append(f"{sub.score:.1f}")
                else:
                    row.append("—")

            grade_info = compute_course_final_grade(s, course) or {}
            final_pct = grade_info.get("percentage")
            row.append(f"{float(final_pct):.1f}%" if final_pct is not None else "—")
            row.append(grade_info.get("letter", "—") or "—")
            writer.writerow(row)

        return response


# ── Lesson ViewSet ────────────────────────────────────────────────────────────

class LessonViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LessonSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        course_id = self.request.query_params.get("course")
        qs = Lesson.objects.all().select_related("course")
        if course_id:
            qs = qs.filter(course_id=course_id)
        if getattr(user, "is_student_role", False) or user.role == "student":
            enrolled = Enrollment.objects.filter(student=user, status=Enrollment.Status.ACTIVE).values_list("course_id", flat=True)
            qs = qs.filter(course_id__in=enrolled)
        elif getattr(user, "is_instructor_role", False) or user.role in ("instructor", "lecturer"):
            qs = qs.filter(course__instructors=user)
        return qs.order_by("order")

    def perform_create(self, serializer):
        user = self.request.user
        course = serializer.validated_data["course"]
        if (getattr(user, "is_instructor_role", False) or user.role in ("instructor", "lecturer")) and not course.instructors.filter(pk=user.pk).exists():
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not instruct this course.")
        serializer.save(published_at=timezone.now())

    @action(detail=True, methods=["post"], url_path="toggle-progress")
    def toggle_progress(self, request, pk=None):
        lesson = self.get_object()
        user = request.user
        from .models import LessonProgress
        record, _ = LessonProgress.objects.get_or_create(student=user, lesson=lesson)
        record.completed = not record.completed
        record.completed_at = timezone.now() if record.completed else None
        record.save(update_fields=["completed", "completed_at"])

        # Update course enrollment progress percentage
        enrollment = Enrollment.objects.filter(student=user, course=lesson.course, status=Enrollment.Status.ACTIVE).first()
        if enrollment:
            total_lessons = Lesson.objects.filter(course=lesson.course).count()
            if total_lessons > 0:
                completed_count = LessonProgress.objects.filter(
                    student=user, lesson__course=lesson.course, completed=True
                ).count()
                enrollment.progress_pct = round((completed_count / total_lessons) * 100, 1)
                enrollment.save(update_fields=["progress_pct"])

        return Response({
            "lesson_id": str(lesson.id),
            "completed": record.completed,
            "progress_pct": float(enrollment.progress_pct) if enrollment else 0.0,
        })


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
