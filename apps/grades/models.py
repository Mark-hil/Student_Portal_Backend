"""
Grade models — full result publication workflow.
Flow: Student registers → Lecturer creates assignment + uploads grades → 
      Lecturer submits batch for review → Academic Officer approves/rejects → 
      Officer publishes → Student sees result + GPA recomputed.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

GRADE_POINTS = {
    "A+": Decimal("4.0"), "A":  Decimal("4.0"), "A-": Decimal("3.7"),
    "B+": Decimal("3.3"), "B":  Decimal("3.0"), "B-": Decimal("2.7"),
    "C+": Decimal("2.3"), "C":  Decimal("2.0"), "C-": Decimal("1.7"),
    "D+": Decimal("1.3"), "D":  Decimal("1.0"), "D-": Decimal("0.7"),
    "F":  Decimal("0.0"),
}


def letter_from_pct(pct: float) -> str:
    if pct >= 97: return "A+"
    if pct >= 93: return "A"
    if pct >= 90: return "A-"
    if pct >= 87: return "B+"
    if pct >= 83: return "B"
    if pct >= 80: return "B-"
    if pct >= 77: return "C+"
    if pct >= 73: return "C"
    if pct >= 70: return "C-"
    if pct >= 67: return "D+"
    if pct >= 63: return "D"
    if pct >= 60: return "D-"
    return "F"


class Assignment(models.Model):
    class Type(models.TextChoices):
        HOMEWORK   = "homework",   "Homework"
        MIDTERM    = "midterm",    "Midterm Exam"
        FINAL      = "final",      "Final Exam"
        QUIZ       = "quiz",       "Quiz"
        PROJECT    = "project",    "Project"
        LAB        = "lab",        "Lab"
        ATTENDANCE = "attendance", "Attendance"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course          = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="assignments")
    title           = models.CharField(max_length=255)
    assignment_type = models.CharField(max_length=20, choices=Type.choices)
    description     = models.TextField(blank=True)
    max_score       = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    weight          = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Percentage weight toward final course grade",
    )
    due_date        = models.DateTimeField(null=True, blank=True, db_index=True)
    is_published    = models.BooleanField(default=False)
    created_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="created_assignments",
    )
    created_at      = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "assignments"
        indexes  = [models.Index(fields=["course", "due_date"])]

    def __str__(self):
        return f"{self.course.code} — {self.title}"


class GradeBatch(models.Model):
    """
    One batch per assignment.
    Tracks the full review lifecycle: draft → pending_review → approved/rejected → published.
    """
    class Status(models.TextChoices):
        DRAFT          = "draft",          "Draft"
        PENDING_REVIEW = "pending_review", "Pending Review"
        REJECTED       = "rejected",       "Rejected"
        APPROVED       = "approved",       "Approved"
        PUBLISHED      = "published",      "Published"

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment      = models.OneToOneField(Assignment, on_delete=models.CASCADE, related_name="grade_batch")
    status          = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    # Lecturer submission
    submitted_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="submitted_batches",
    )
    submitted_at    = models.DateTimeField(null=True, blank=True)
    submission_note = models.TextField(blank=True)
    # Officer review
    reviewed_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reviewed_batches",
    )
    reviewed_at     = models.DateTimeField(null=True, blank=True)
    review_notes    = models.TextField(blank=True)
    # Publication
    published_at    = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "grade_batches"
        indexes  = [models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.assignment} [{self.status}]"

    @property
    def grade_count(self):
        return self.assignment.grades.count()

    def submit(self, lecturer, note: str = ""):
        """Lecturer submits batch for officer review."""
        if self.status != self.Status.DRAFT:
            raise ValueError(f"Cannot submit a batch with status '{self.status}'.")
        self.status          = self.Status.PENDING_REVIEW
        self.submitted_by    = lecturer
        self.submitted_at    = timezone.now()
        self.submission_note = note
        self.save(update_fields=["status", "submitted_by", "submitted_at", "submission_note"])
        self._notify_officers()

    def approve(self, officer):
        """Academic officer approves — grades not yet visible to students."""
        if self.status != self.Status.PENDING_REVIEW:
            raise ValueError(f"Cannot approve a batch with status '{self.status}'.")
        self.status      = self.Status.APPROVED
        self.reviewed_by = officer
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        self._notify_lecturer("approved")

    def reject(self, officer, notes: str):
        """Academic officer rejects — returns to lecturer with notes."""
        if self.status not in (self.Status.PENDING_REVIEW, self.Status.APPROVED):
            raise ValueError(f"Cannot reject a batch with status '{self.status}'.")
        self.status       = self.Status.REJECTED
        self.reviewed_by  = officer
        self.reviewed_at  = timezone.now()
        self.review_notes = notes
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_notes"])
        self._notify_lecturer("rejected")

    def publish(self, officer):
        """
        Academic officer publishes — marks all grades is_published=True.
        Students can now see their result. Triggers GPA recompute.
        """
        if self.status not in (self.Status.APPROVED, self.Status.PENDING_REVIEW):
            raise ValueError(f"Cannot publish a batch with status '{self.status}'.")
        self.status      = self.Status.PUBLISHED
        self.reviewed_by = officer
        self.reviewed_at = timezone.now()
        self.published_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "published_at"])
        # Flip all grades to published
        self.assignment.grades.update(is_published=True)
        self._notify_students()
        self._trigger_gpa_recompute()

    # ── internal ──────────────────────────────────────────────────────────
    def _notify_officers(self):
        from apps.notifications.tasks import create_notification
        from django.contrib.auth import get_user_model
        User = get_user_model()
        officers = User.objects.filter(role__in=["staff", "admin"], is_active=True)
        for officer in officers:
            create_notification.delay(
                user_id=str(officer.pk),
                notif_type="grade_review_requested",
                title=f"Grade Review Requested: {self.assignment.course.code}",
                body=(
                    f"{self.submitted_by.full_name} submitted grades for "
                    f"{self.assignment.title} ({self.assignment.course.code}) for your review."
                ),
                data={"batch_id": str(self.pk), "course_code": self.assignment.course.code},
            )

    def _notify_lecturer(self, action: str):
        from apps.notifications.tasks import create_notification, send_email_notification
        if not self.submitted_by:
            return
        notif_type = "grade_batch_approved" if action == "approved" else "grade_batch_rejected"
        title = f"Grade Batch {action.title()}: {self.assignment.course.code}"
        body  = (
            f"Your grade submission for {self.assignment.title} "
            f"({self.assignment.course.code}) has been {action}."
        )
        if action == "rejected" and self.review_notes:
            body += f" Notes: {self.review_notes}"
        create_notification.delay(
            user_id=str(self.submitted_by.pk),
            notif_type=notif_type, title=title, body=body,
            data={"batch_id": str(self.pk)},
        )
        send_email_notification.delay(
            user_id=str(self.submitted_by.pk),
            subject=f"[UniPortal] {title}", body=body,
        )

    def _notify_students(self):
        from apps.notifications.tasks import create_notification, send_email_notification
        for grade in self.assignment.grades.select_related("student"):
            body = (
                f"Your result for {self.assignment.title} "
                f"({self.assignment.course.code}) has been published: {grade.letter_grade}."
            )
            create_notification.delay(
                user_id=str(grade.student.pk),
                notif_type="grade_posted",
                title=f"Result Published: {self.assignment.course.code}",
                body=body,
                data={"batch_id": str(self.pk), "grade_id": str(grade.pk)},
            )
            send_email_notification.delay(
                user_id=str(grade.student.pk),
                subject=f"[UniPortal] Result Published: {self.assignment.course.code}",
                body=body,
            )

    def _trigger_gpa_recompute(self):
        from apps.grades.tasks import recompute_gpa_for_student
        semester = self.assignment.course.semester or "unknown"
        seen = set()
        for grade in self.assignment.grades.select_related("student"):
            if grade.student.pk not in seen:
                seen.add(grade.student.pk)
                recompute_gpa_for_student.delay(
                    student_id=str(grade.student.pk),
                    semester=semester,
                    semester_label=semester,
                )


class Grade(models.Model):
    """One grade entry per student per assignment. Visible to student only when is_published=True."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grades")
    assignment  = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="grades")
    score       = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    feedback    = models.TextField(blank=True)
    graded_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name="graded_entries",
    )
    is_published = models.BooleanField(default=False, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    graded_at    = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(default=timezone.now)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table        = "grades"
        unique_together = [("student", "assignment")]
        indexes         = [models.Index(fields=["student", "is_published"])]

    def __str__(self):
        return f"{self.student.email} — {self.assignment.title}: {self.score}"

    @property
    def percentage(self) -> float | None:
        if self.score is None or self.assignment.max_score == 0:
            return None
        return float(self.score / self.assignment.max_score * 100)

    @property
    def letter_grade(self) -> str:
        pct = self.percentage
        return "N/A" if pct is None else letter_from_pct(pct)

    @property
    def grade_points(self) -> Decimal | None:
        return GRADE_POINTS.get(self.letter_grade)

    @property
    def batch_status(self) -> str:
        try:
            return self.assignment.grade_batch.status
        except GradeBatch.DoesNotExist:
            return "draft"


class SemesterRecord(models.Model):
    """
    One row per student per semester.
    Stores Semester GPA and Cumulative GPA side by side.

    Semester GPA  = Σ(grade_points × credits) / Σ(credits)  — one term only
    Cumulative GPA = Σ(grade_points × credits) / Σ(credits)  — ALL completed terms
    """
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="semester_records")
    semester     = models.CharField(max_length=20, db_index=True)
    semester_label = models.CharField(max_length=30)
    # Semester
    semester_gpa                = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    semester_credits_attempted  = models.PositiveSmallIntegerField(default=0)
    semester_credits_earned     = models.PositiveSmallIntegerField(default=0)
    semester_quality_points     = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # Cumulative
    cumulative_gpa              = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    cumulative_credits_attempted = models.PositiveSmallIntegerField(default=0)
    cumulative_credits_earned   = models.PositiveSmallIntegerField(default=0)
    cumulative_quality_points   = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    status     = models.CharField(max_length=20, choices=[("in_progress","In Progress"),("completed","Completed"),("withdrawn","Withdrawn")], default="in_progress")
    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table        = "semester_records"
        unique_together = [("student", "semester")]
        indexes         = [models.Index(fields=["student", "semester"])]
        ordering        = ["-semester"]

    def __str__(self):
        return f"{self.student.email} — {self.semester_label} (sem:{self.semester_gpa} / cum:{self.cumulative_gpa})"


class Transcript(models.Model):
    """Official grade record — one row per student per course per semester."""
    id                 = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student            = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transcripts")
    course             = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="transcripts")
    semester           = models.CharField(max_length=20, db_index=True)
    semester_label     = models.CharField(max_length=30)
    final_grade        = models.CharField(max_length=5, blank=True)
    grade_points       = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    credits_attempted  = models.PositiveSmallIntegerField(default=0)
    credits_earned     = models.PositiveSmallIntegerField(default=0)
    quality_points     = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    computed_at        = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table        = "transcripts"
        unique_together = [("student", "course", "semester")]
        indexes         = [models.Index(fields=["student", "semester"])]

    def __str__(self):
        return f"{self.student.email} — {self.course.code} ({self.semester}): {self.final_grade}"
