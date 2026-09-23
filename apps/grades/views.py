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

from .models import Grade, GradeBatch, Assignment, SemesterRecord, Transcript, Submission
from .serializers import (
    GradeSerializer, AssignmentSerializer, AssignmentCreateSerializer,
    GradeBatchListSerializer, GradeBatchDetailSerializer,
    BatchGradeEntrySerializer, SubmitBatchSerializer, RejectBatchSerializer,
    TranscriptRowSerializer, SemesterRecordSerializer,
    SubmissionSerializer, SubmissionCreateSerializer,
)
from .gpa import compute_semester_gpa, compute_cumulative_gpa, letter_from_pct
from core.permissions import IsInstructor
from core.pagination import StandardResultsPagination

logger = logging.getLogger(__name__)


def get_current_semester_info():
    """Retrieve the current active semester and label dynamically."""
    try:
        from apps.courses.models import RegistrationWindow
        window = RegistrationWindow.objects.filter(is_active=True).order_by("-opens_at").first()
        if window:
            return window.semester, window.semester_label or window.semester
    except Exception:
        pass
    return "2025-SPRING", "Spring 2025"


# ── Assignment viewset (Lecturer + Student Submissions) ────────────────────────
class AssignmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    pagination_class   = StandardResultsPagination

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AssignmentCreateSerializer
        return AssignmentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == "instructor":
            qs = Assignment.objects.select_related("course").filter(
                course__instructors=user
            )
        elif user.role in ("staff", "admin"):
            qs = Assignment.objects.select_related("course").all()
        else:
            # Students see published assignments for their enrolled courses
            from apps.courses.models import Enrollment
            enrolled_courses = Enrollment.objects.filter(
                student=user, status=Enrollment.Status.ACTIVE
            ).values_list("course_id", flat=True)
            qs = Assignment.objects.select_related("course").filter(
                course_id__in=enrolled_courses, is_published=True
            )

        course_id = self.request.query_params.get("course")
        if course_id:
            qs = qs.filter(course_id=course_id)
        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="publish", permission_classes=[IsAuthenticated, IsInstructor])
    def publish(self, request, pk=None):
        assignment = self.get_object()
        assignment.is_published = not assignment.is_published
        assignment.save(update_fields=["is_published"])
        return Response({"is_published": assignment.is_published})

    @action(detail=True, methods=["post"], url_path="submit", permission_classes=[IsAuthenticated])
    def submit(self, request, pk=None):
        """Student submits an assignment."""
        try:
            assignment = Assignment.objects.get(pk=pk)
        except Assignment.DoesNotExist:
            return Response({"error": "not_found", "detail": "Assignment not found."}, status=status.HTTP_404_NOT_FOUND)

        from apps.courses.models import Enrollment
        if not Enrollment.objects.filter(student=request.user, course=assignment.course, status=Enrollment.Status.ACTIVE).exists() and request.user.role not in ("admin",):
            return Response({"error": "not_enrolled", "detail": "You must be actively enrolled in this course to submit work."}, status=status.HTTP_403_FORBIDDEN)

        is_late = False
        if assignment.due_date and timezone.now() > assignment.due_date:
            is_late = True

        serializer = SubmissionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        submission, _ = Submission.objects.update_or_create(
            assignment=assignment,
            student=request.user,
            defaults={
                "file": serializer.validated_data.get("file"),
                "text_content": serializer.validated_data.get("text_content", ""),
                "status": Submission.Status.LATE if is_late else Submission.Status.SUBMITTED,
                "submitted_at": timezone.now(),
            }
        )
        return Response(SubmissionSerializer(submission, context={"request": request}).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="my-submission", permission_classes=[IsAuthenticated])
    def my_submission(self, request, pk=None):
        """Student views their submission for an assignment."""
        submission = Submission.objects.filter(assignment_id=pk, student=request.user).first()
        if not submission:
            return Response(None, status=status.HTTP_200_OK)
        return Response(SubmissionSerializer(submission, context={"request": request}).data)

    @action(detail=True, methods=["get"], url_path="submissions", permission_classes=[IsAuthenticated, IsInstructor])
    def submissions(self, request, pk=None):
        """Lecturer views all student submissions for an assignment."""
        assignment = self.get_object()
        submissions = Submission.objects.filter(assignment=assignment).select_related("student", "file").order_by("-submitted_at")
        return Response(SubmissionSerializer(submissions, many=True, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="grade-submission", permission_classes=[IsAuthenticated, IsInstructor])
    def grade_submission(self, request, pk=None):
        """Lecturer grades an individual student submission and updates Grade record."""
        assignment = self.get_object()
        submission_id = request.data.get("submission_id")
        score = request.data.get("score")
        feedback = request.data.get("feedback", "")

        if not submission_id or score is None:
            return Response({"error": "missing_fields", "detail": "submission_id and score are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            score = float(score)
        except (ValueError, TypeError):
            return Response({"error": "invalid_score", "detail": "Score must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        if score < 0 or score > float(assignment.max_score):
            return Response({"error": "score_out_of_bounds", "detail": f"Score must be between 0 and {assignment.max_score}."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            submission = Submission.objects.get(pk=submission_id, assignment=assignment)
        except Submission.DoesNotExist:
            return Response({"error": "not_found", "detail": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)

        submission.score = score
        submission.feedback = feedback
        submission.status = Submission.Status.GRADED
        submission.graded_at = timezone.now()
        submission.save(update_fields=["score", "feedback", "status", "graded_at"])

        # Sync/upsert Grade record
        from .models import Grade
        Grade.objects.update_or_create(
            student=submission.student,
            assignment=assignment,
            defaults={
                "score": score,
                "feedback": feedback,
                "graded_by": request.user,
                "graded_at": timezone.now(),
            }
        )

        return Response(SubmissionSerializer(submission, context={"request": request}).data, status=status.HTTP_200_OK)


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
            from apps.users.models import AuditLog
            from apps.users.services.audit_service import AuditService
            course_code = getattr(getattr(batch, "course", None), "code", "Unknown")
            AuditService.log_event(
                action="GRADE_BATCH_APPROVED",
                category=AuditLog.Category.ACADEMICS,
                actor=request.user,
                request=request,
                status=AuditLog.Status.SUCCESS,
                target_type="GradeBatch",
                target_id=str(batch.id),
                target_repr=f"Grade Batch {batch.id} ({course_code})",
                description=f"Academic Officer '{request.user.email}' approved grade batch for {course_code} ({batch.academic_year} Sem {batch.semester}).",
                metadata={"batch_id": str(batch.id), "course": course_code},
            )
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
            from apps.users.models import AuditLog
            from apps.users.services.audit_service import AuditService
            course_code = getattr(getattr(batch, "course", None), "code", "Unknown")
            AuditService.log_event(
                action="GRADE_BATCH_PUBLISHED",
                category=AuditLog.Category.ACADEMICS,
                actor=request.user,
                request=request,
                status=AuditLog.Status.SUCCESS,
                target_type="GradeBatch",
                target_id=str(batch.id),
                target_repr=f"Grade Batch {batch.id} ({course_code})",
                description=f"Academic Officer '{request.user.email}' officially published grades for {course_code} to student transcripts.",
                metadata={"batch_id": str(batch.id), "course": course_code},
            )
        except ValueError as e:
            return Response({"error": "invalid_status", "detail": str(e)}, status=400)
        logger.info("Batch %s published by %s — students notified", pk, request.user.email)
        return Response(GradeBatchDetailSerializer(batch).data)

    # ── LECTURER/OFFICER: export CSV roster template ─────────────────────────
    @action(detail=True, methods=["get"], url_path="export-csv")
    def export_csv(self, request, pk=None):
        import csv
        from django.http import HttpResponse
        batch = self.get_object()
        course = batch.assignment.course
        from apps.courses.models import Enrollment

        enrollments = (
            Enrollment.objects
            .filter(course=course, status=Enrollment.Status.ACTIVE)
            .select_related("student")
            .order_by("student__last_name", "student__first_name")
        )
        grades_by_student = {g.student_id: g for g in batch.assignment.grades.all()}

        response = HttpResponse(content_type="text/csv")
        safe_title = "".join(c for c in batch.assignment.title if c.isalnum() or c in (" ", "_", "-")).strip()
        response["Content-Disposition"] = f'attachment; filename="grade_roster_{course.code}_{safe_title}.csv"'

        writer = csv.writer(response)
        writer.writerow(["student_id", "student_name", "email", "score", "feedback"])
        for e in enrollments:
            s = e.student
            g = grades_by_student.get(s.id)
            score_val = str(g.score) if g and g.score is not None else ""
            feedback_val = g.feedback if g and g.feedback else ""
            writer.writerow([s.student_id or str(s.id), s.full_name, s.email, score_val, feedback_val])

        return response

    # ── LECTURER: import CSV grade spreadsheet ──────────────────────────────
    @action(detail=True, methods=["post"], url_path="import-csv")
    def import_csv(self, request, pk=None):
        import csv
        import io
        from decimal import Decimal
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        User = get_user_model()
        batch = self.get_object()

        if batch.status not in (GradeBatch.Status.DRAFT, GradeBatch.Status.REJECTED):
            return Response(
                {"error": "not_editable", "detail": "Batch cannot be edited in its current status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        csv_file = request.FILES.get("file")
        if not csv_file:
            return Response({"error": "no_file", "detail": "Please provide a CSV file."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            decoded = csv_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded))
        except Exception as e:
            return Response({"error": "invalid_csv", "detail": f"Failed to parse CSV file: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        processed = 0
        errors = []
        for row_num, row in enumerate(reader, start=2):
            raw_id = (row.get("student_id") or row.get("email") or "").strip()
            raw_score = (row.get("score") or "").strip()
            raw_feedback = (row.get("feedback") or "").strip()

            if not raw_id or not raw_score:
                continue

            try:
                score_num = Decimal(raw_score)
                if score_num < 0 or score_num > batch.assignment.max_score:
                    errors.append(f"Row {row_num}: Score {raw_score} exceeds limits (0 - {batch.assignment.max_score})")
                    continue
            except Exception:
                errors.append(f"Row {row_num}: Invalid score '{raw_score}'")
                continue

            student = User.objects.filter(Q(student_id=raw_id) | Q(email=raw_id) | Q(id__iexact=raw_id)).first()
            if not student:
                errors.append(f"Row {row_num}: Student '{raw_id}' not found")
                continue

            pct = float((score_num / batch.assignment.max_score) * 100) if batch.assignment.max_score else 0.0
            letter = letter_from_pct(pct)

            Grade.objects.update_or_create(
                assignment=batch.assignment,
                student=student,
                defaults={
                    "score": score_num,
                    "feedback": raw_feedback,
                    "graded_by": request.user,
                    "graded_at": timezone.now(),
                }
            )
            processed += 1

        return Response({
            "imported_count": processed,
            "errors": errors,
            "detail": f"Imported {processed} grades with {len(errors)} errors.",
            "total": Grade.objects.filter(assignment=batch.assignment).count(),
        })


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

        curr_sem, curr_label = get_current_semester_info()
        records       = SemesterRecord.objects.filter(student=request.user).order_by("semester")
        current_rec   = records.filter(semester=curr_sem).first()
        all_recs      = list(records)

        sem_gpa = current_rec.semester_gpa  if current_rec else compute_semester_gpa(request.user, curr_sem)
        cum_gpa = current_rec.cumulative_gpa if current_rec else compute_cumulative_gpa(request.user)

        data = {
            "semester_gpa":           sem_gpa,
            "cumulative_gpa":         cum_gpa,
            "current_semester":       curr_sem,
            "current_semester_label": curr_label,
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

    @action(detail=False, methods=["get"], url_path="transcript/pdf")
    def transcript_pdf(self, request):
        """Generates downloadable unofficial transcript PDF with watermark."""
        from django.http import HttpResponse
        from .pdf import build_transcript_pdf

        rows = Transcript.objects.filter(student=request.user).select_related("course").order_by("-semester", "course__code")
        records = {r.semester: r for r in SemesterRecord.objects.filter(student=request.user)}
        semesters: dict = {}
        for row in rows:
            key = row.semester
            if key not in semesters:
                semesters[key] = {"semester": key, "label": row.semester_label, "courses": []}
            semesters[key]["courses"].append(TranscriptRowSerializer(row).data)

        semesters_list = []
        for key, sem in semesters.items():
            rec = records.get(key)
            sem["semester_gpa"]      = str(rec.semester_gpa)     if rec and rec.semester_gpa     else "—"
            sem["cumulative_gpa"]    = str(rec.cumulative_gpa)   if rec and rec.cumulative_gpa   else "—"
            sem["credits_attempted"] = rec.semester_credits_attempted if rec else 0
            sem["credits_earned"]    = rec.semester_credits_earned    if rec else 0
            semesters_list.append(sem)

        curr_sem, _ = get_current_semester_info()
        current_rec = records.get(curr_sem) or SemesterRecord.objects.filter(student=request.user).order_by("-semester").first()
        cum_gpa = current_rec.cumulative_gpa if current_rec and current_rec.cumulative_gpa else compute_cumulative_gpa(request.user)

        cumulative_stats = {
            "cumulative_gpa": str(cum_gpa) if cum_gpa else "—",
            "cumulative_credits_attempted": current_rec.cumulative_credits_attempted if current_rec else sum(s.get("credits_attempted", 0) for s in semesters_list),
            "cumulative_credits_earned": current_rec.cumulative_credits_earned if current_rec else sum(s.get("credits_earned", 0) for s in semesters_list),
            "cumulative_quality_points": str(current_rec.cumulative_quality_points) if current_rec and current_rec.cumulative_quality_points else "—",
        }

        pdf_buffer = build_transcript_pdf(request.user, semesters_list, cumulative_stats)
        student_id_str = request.user.student_id or str(request.user.id)[:8]
        response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="unofficial_transcript_{student_id_str}.pdf"'
        return response

    @action(detail=False, methods=["get"], url_path="course-summary")
    def course_summary(self, request):
        from apps.courses.models import Enrollment
        from .gpa import compute_course_final_grade
        curr_sem, _ = get_current_semester_info()
        enrollments = (
            Enrollment.objects
            .filter(student=request.user, status="active", course__semester=curr_sem)
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
        curr_sem, curr_label = get_current_semester_info()
        semester = request.data.get("semester", curr_sem)
        label    = request.data.get("semester_label", curr_label)
        recompute_gpa_for_student.delay(str(request.user.id), semester, label)
        cache.delete(f"gpa_summary:{request.user.id}")
        cache.delete(f"transcript:{request.user.id}")
        return Response({"detail": "GPA recomputation queued."})
