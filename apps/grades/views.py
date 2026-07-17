"""
Grades API views — complete 3-role result publication workflow.

Student   : GET /grades/                 → published grades only
             GET /grades/gpa-summary/    → semester + cumulative GPA
             GET /grades/transcript/     → official transcript by semester
             GET /grades/course-summary/ → per-course current grade

Lecturer  : GET/POST /grades/assignments/           → manage assignments
             POST /grades/assignments/{id}/publish/ → toggle published flag
             GET  /grades/batches/                  → my batches
             GET  /grades/batches/{id}/             → batch detail with all grades
             POST /grades/batches/{id}/upload/      → upload / overwrite scores
             PATCH /grades/batches/{id}/submit/     → submit for officer review

Officer   : GET  /grades/batches/?role=officer  → pending review queue
             PATCH /grades/batches/{id}/approve/ → approve
             PATCH /grades/batches/{id}/reject/  → reject with notes
             PATCH /grades/batches/{id}/publish/ → publish to students
"""
import logging
from django.db.models import Avg, Count
from django.core.cache import cache
from django.utils import timezone
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .models import Grade, GradeBatch, Assignment, SemesterRecord, Transcript
from .serializers import (
    GradeSerializer, AssignmentSerializer, AssignmentCreateSerializer,
    GradeBatchListSerializer, GradeBatchDetailSerializer,
    BatchGradeEntrySerializer, SubmitBatchSerializer, RejectBatchSerializer,
    TranscriptRowSerializer, SemesterRecordSerializer,
)
from .gpa import compute_semester_gpa, compute_cumulative_gpa
from core.permissions import IsInstructor
from core.pagination import StandardResultsPagination

logger = logging.getLogger(__name__)

CURRENT_SEMESTER       = "2025-SPRING"
CURRENT_SEMESTER_LABEL = "Spring 2025"


# ── Assignment viewset (Lecturer) ──────────────────────────────────────────────
class AssignmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsInstructor]
    pagination_class   = StandardResultsPagination

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AssignmentCreateSerializer
        return AssignmentSerializer

    def get_queryset(self):
        qs = Assignment.objects.select_related("course").filter(
            course__instructors=self.request.user
        )
        course_id = self.request.query_params.get("course")
        if course_id:
            qs = qs.filter(course_id=course_id)
        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="publish")
    def publish(self, request, pk=None):
        assignment = self.get_object()
        assignment.is_published = not assignment.is_published
        assignment.save(update_fields=["is_published"])
        return Response({"is_published": assignment.is_published})


# ── GradeBatch viewset (Lecturer + Officer) ────────────────────────────────────
class GradeBatchViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    pagination_class   = None  # Return plain list for batches

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GradeBatchDetailSerializer
        return GradeBatchListSerializer

    def get_queryset(self):
        user = self.request.user
        role = self.request.query_params.get("role", "")
        qs   = GradeBatch.objects.select_related(
            "assignment__course", "submitted_by", "reviewed_by"
        )
        if user.role in ("staff", "admin") or role == "officer":
            # Officers see all pending/approved/rejected
            return qs.order_by("-submitted_at")
        else:
            # Lecturers see only their own courses' batches
            return qs.filter(
                assignment__course__instructors=user
            ).order_by("-created_at")

    # ── LECTURER: upload scores ──────────────────────────────────────────────
    @action(detail=True, methods=["post"], url_path="upload")
    def upload(self, request, pk=None):
        batch = self.get_object()
        if batch.status not in (GradeBatch.Status.DRAFT, GradeBatch.Status.REJECTED):
            return Response(
                {"error": "not_editable", "detail": "Batch cannot be edited in its current status."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = BatchGradeEntrySerializer(data=request.data.get("grades", []), many=True)
        serializer.is_valid(raise_exception=True)

        from django.contrib.auth import get_user_model
        from django.db.models import Q
        import uuid
        User = get_user_model()

        provided_ids = [entry["student_id"] for entry in serializer.validated_data]
        valid_uuids = []
        for pid in provided_ids:
            try:
                valid_uuids.append(uuid.UUID(str(pid)))
            except ValueError:
                pass

        users = User.objects.filter(Q(id__in=valid_uuids) | Q(student_id__in=provided_ids))
        
        user_map = {}
        for u in users:
            user_map[str(u.id)] = u
            if u.student_id:
                user_map[str(u.student_id)] = u

        invalid_ids = []
        for pid in provided_ids:
            if str(pid) not in user_map:
                invalid_ids.append(pid)

        if invalid_ids:
            return Response(
                {"error": "invalid_students", "detail": f"Could not find students for IDs: {', '.join(invalid_ids)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        created, updated = 0, 0
        for entry in serializer.validated_data:
            student = user_map[str(entry["student_id"])]
            grade, created_flag = Grade.objects.update_or_create(
                student_id=student.id,
                assignment=batch.assignment,
                defaults={
                    "score":      entry["score"],
                    "feedback":   entry.get("feedback", ""),
                    "graded_by":  request.user,
                    "graded_at":  timezone.now(),
                    "is_published": False,
                },
            )
            if created_flag:
                created += 1
            else:
                updated += 1

        logger.info("Batch %s: uploaded %d new, %d updated grades by %s", pk, created, updated, request.user.email)
        return Response({"created": created, "updated": updated, "total": Grade.objects.filter(assignment=batch.assignment).count()})

    # ── LECTURER: submit for review ──────────────────────────────────────────
    @action(detail=True, methods=["patch"], url_path="submit")
    def submit(self, request, pk=None):
        batch = self.get_object()
        if batch.assignment.course.instructors.filter(pk=request.user.pk).exists() is False and request.user.role not in ("admin",):
            return Response({"error": "forbidden", "detail": "Not your course."}, status=403)
        serializer = SubmitBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            batch.submit(request.user, serializer.validated_data.get("note", ""))
        except ValueError as e:
            return Response({"error": "invalid_status", "detail": str(e)}, status=400)
        logger.info("Batch %s submitted for review by %s", pk, request.user.email)
        return Response(GradeBatchDetailSerializer(batch).data)

    # ── OFFICER: approve ─────────────────────────────────────────────────────
    @action(detail=True, methods=["patch"], url_path="approve")
    def approve(self, request, pk=None):
        if request.user.role not in ("staff", "admin"):
            return Response({"error": "forbidden", "detail": "Only academic officers can approve batches."}, status=403)
        batch = self.get_object()
        try:
            batch.approve(request.user)
        except ValueError as e:
            return Response({"error": "invalid_status", "detail": str(e)}, status=400)
        logger.info("Batch %s approved by %s", pk, request.user.email)
        return Response(GradeBatchDetailSerializer(batch).data)

    # ── OFFICER: reject ──────────────────────────────────────────────────────
    @action(detail=True, methods=["patch"], url_path="reject")
    def reject(self, request, pk=None):
        if request.user.role not in ("staff", "admin"):
            return Response({"error": "forbidden", "detail": "Only academic officers can reject batches."}, status=403)
        batch = self.get_object()
        serializer = RejectBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            batch.reject(request.user, serializer.validated_data["notes"])
        except ValueError as e:
            return Response({"error": "invalid_status", "detail": str(e)}, status=400)
        logger.info("Batch %s rejected by %s", pk, request.user.email)
        return Response(GradeBatchDetailSerializer(batch).data)

    # ── OFFICER: publish ─────────────────────────────────────────────────────
    @action(detail=True, methods=["patch"], url_path="publish")
    def publish(self, request, pk=None):
        if request.user.role not in ("staff", "admin"):
            return Response({"error": "forbidden", "detail": "Only academic officers can publish results."}, status=403)
        batch = self.get_object()
        try:
            batch.publish(request.user)
        except ValueError as e:
            return Response({"error": "invalid_status", "detail": str(e)}, status=400)
        logger.info("Batch %s published by %s — students notified", pk, request.user.email)
        return Response(GradeBatchDetailSerializer(batch).data)


# ── Grade viewset (Student) ────────────────────────────────────────────────────
class GradeViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = GradeSerializer
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        qs = (
            Grade.objects
            .filter(student=self.request.user, is_published=True)
            .select_related("assignment__course", "assignment__grade_batch")
            .order_by("-graded_at")
        )
        course_id = self.request.query_params.get("course")
        if course_id:
            qs = qs.filter(assignment__course_id=course_id)
        semester = self.request.query_params.get("semester")
        if semester:
            qs = qs.filter(assignment__course__semester=semester)
        return qs

    @action(detail=False, methods=["get"], url_path="gpa-summary")
    def gpa_summary(self, request):
        cache_key = f"gpa_summary:{request.user.id}"
        cached    = cache.get(cache_key)
        if cached:
            return Response(cached)

        records       = SemesterRecord.objects.filter(student=request.user).order_by("semester")
        current_rec   = records.filter(semester=CURRENT_SEMESTER).first()
        all_recs      = list(records)

        sem_gpa = current_rec.semester_gpa  if current_rec else compute_semester_gpa(request.user, CURRENT_SEMESTER)
        cum_gpa = current_rec.cumulative_gpa if current_rec else compute_cumulative_gpa(request.user)

        data = {
            "semester_gpa":           sem_gpa,
            "cumulative_gpa":         cum_gpa,
            "current_semester":       CURRENT_SEMESTER,
            "current_semester_label": CURRENT_SEMESTER_LABEL,
            "credits_completed":      current_rec.cumulative_credits_earned  if current_rec else 0,
            "credits_this_semester":  current_rec.semester_credits_attempted if current_rec else 0,
            "semester_history":       SemesterRecordSerializer(all_recs, many=True).data,
        }
        cache.set(cache_key, data, 60 * 10)
        return Response(data)

    @action(detail=False, methods=["get"], url_path="transcript")
    def transcript(self, request):
        cache_key = f"transcript:{request.user.id}"
        cached    = cache.get(cache_key)
        if cached:
            return Response(cached)

        rows    = Transcript.objects.filter(student=request.user).select_related("course").order_by("-semester", "course__code")
        records = {r.semester: r for r in SemesterRecord.objects.filter(student=request.user)}
        semesters: dict = {}
        for row in rows:
            key = row.semester
            if key not in semesters:
                semesters[key] = {"semester": key, "label": row.semester_label, "courses": []}
            semesters[key]["courses"].append(TranscriptRowSerializer(row).data)

        result = []
        for key, sem in semesters.items():
            rec = records.get(key)
            sem["semester_gpa"]     = str(rec.semester_gpa)     if rec and rec.semester_gpa     else None
            sem["cumulative_gpa"]   = str(rec.cumulative_gpa)   if rec and rec.cumulative_gpa   else None
            sem["credits_attempted"] = rec.semester_credits_attempted if rec else 0
            sem["credits_earned"]    = rec.semester_credits_earned    if rec else 0
            result.append(sem)

        cache.set(cache_key, result, 60 * 30)
        return Response(result)

    @action(detail=False, methods=["get"], url_path="course-summary")
    def course_summary(self, request):
        from apps.courses.models import Enrollment
        from .gpa import compute_course_final_grade
        enrollments = (
            Enrollment.objects
            .filter(student=request.user, status="active", course__semester=CURRENT_SEMESTER)
            .select_related("course")
        )
        result = []
        for e in enrollments:
            grade_info = compute_course_final_grade(request.user, e.course)
            result.append({
                "course_id":     str(e.course.id),
                "course_code":   e.course.code,
                "course_title":  e.course.title,
                "credits":       e.course.credits,
                "progress_pct":  float(e.progress_pct),
                "current_grade": grade_info["letter"],
                "current_pct":   grade_info["percentage"],
                "grade_points":  str(grade_info["grade_points"]) if grade_info["grade_points"] else None,
            })
        return Response(result)

    @action(detail=False, methods=["post"], url_path="recompute")
    def recompute(self, request):
        from .tasks import recompute_gpa_for_student
        semester = request.data.get("semester", CURRENT_SEMESTER)
        label    = request.data.get("semester_label", CURRENT_SEMESTER_LABEL)
        recompute_gpa_for_student.delay(str(request.user.id), semester, label)
        cache.delete(f"gpa_summary:{request.user.id}")
        cache.delete(f"transcript:{request.user.id}")
        return Response({"detail": "GPA recomputation queued."})
