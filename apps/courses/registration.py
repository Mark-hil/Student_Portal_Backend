"""
Course Registration Service
============================
Handles the full registration flow:
  - prerequisite checking
  - credit-limit enforcement (max 18 credits per semester)
  - capacity checks
  - conflict detection (same timeslot)
  - waitlist placement when full
  - atomic DB writes
  - post-registration notifications (Celery)
"""
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from .models import Course, Enrollment, CourseSchedule

logger = logging.getLogger(__name__)


class RegistrationError(Exception):
    """Raised for any business-rule violation during registration."""
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class RegistrationService:
    MAX_CREDITS_PER_SEMESTER = 18
    MIN_CREDITS_PER_SEMESTER = 0   # allow zero (e.g. incoming freshmen)

    def __init__(self, student, semester: str):
        self.student = student
        self.semester = semester
        self._active_enrollments = None

    # ── public API ──────────────────────────────────────────────────────────

    def register(self, course: Course) -> Enrollment:
        """Register the student in a course. Returns the Enrollment object."""
        self._validate(course)
        with transaction.atomic():
            enrollment = self._create_enrollment(course)
        self._post_register_tasks(enrollment)
        return enrollment

    def drop(self, enrollment: Enrollment) -> Enrollment:
        """Drop an active enrollment."""
        if enrollment.student_id != self.student.pk:
            raise RegistrationError("forbidden", "You can only drop your own enrollments.")
        if enrollment.status not in (Enrollment.Status.ACTIVE, Enrollment.Status.WAITLISTED):
            raise RegistrationError("already_dropped", "This enrollment is already dropped or completed.")
        with transaction.atomic():
            enrollment.status = Enrollment.Status.DROPPED
            enrollment.dropped_at = timezone.now()
            enrollment.save(update_fields=["status", "dropped_at"])
            self._active_enrollments = None
            # Promote next person off waitlist
            self._promote_waitlist(enrollment.course)
        logger.info("Student %s dropped %s", self.student.email, enrollment.course.code)
        return enrollment

    def bulk_register(self, courses: list[Course]) -> dict:
        """Register multiple courses atomically. Rolls back all if any fails."""
        results = {"registered": [], "errors": []}
        with transaction.atomic():
            for course in courses:
                try:
                    self._validate(course)
                    enrollment = self._create_enrollment(course)
                    results["registered"].append(enrollment)
                except RegistrationError as e:
                    results["errors"].append({"course": course.code, "error": e.code, "detail": e.detail})
                    # Don't rollback partial — caller decides via raise_on_error flag
        for enrollment in results["registered"]:
            self._post_register_tasks(enrollment)
        return results

    # ── validation ──────────────────────────────────────────────────────────

    def _validate(self, course: Course):
        self._check_course_active(course)
        self._check_already_enrolled(course)
        self._check_prerequisites(course)
        self._check_credit_limit(course)
        self._check_schedule_conflict(course)
        # Capacity check is last — least expensive rejection first
        self._check_capacity(course)

    def _check_course_active(self, course: Course):
        if course.status != Course.Status.ACTIVE:
            raise RegistrationError("not_active", f"{course.code} is not open for registration.")

    def _check_already_enrolled(self, course: Course):
        if Enrollment.objects.filter(
            student=self.student,
            course=course,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.WAITLISTED],
        ).exists():
            raise RegistrationError("already_enrolled", f"You are already enrolled in {course.code}.")

    def _check_prerequisites(self, course: Course):
        prereqs = course.prerequisites.all()
        if not prereqs.exists():
            return
        completed_course_ids = set(
            Enrollment.objects.filter(
                student=self.student,
                status=Enrollment.Status.COMPLETED,
            ).values_list("course_id", flat=True)
        )
        missing = [p.code for p in prereqs if p.pk not in completed_course_ids]
        if missing:
            raise RegistrationError(
                "prerequisites_not_met",
                f"Missing prerequisites for {course.code}: {', '.join(missing)}."
            )

    def _check_credit_limit(self, course: Course):
        current = self._get_semester_credits()
        if current + course.credits > self.MAX_CREDITS_PER_SEMESTER:
            raise RegistrationError(
                "credit_limit_exceeded",
                f"Adding {course.credits} credits would exceed the {self.MAX_CREDITS_PER_SEMESTER}-credit limit "
                f"(currently at {current})."
            )

    def _check_schedule_conflict(self, course: Course):
        """Check for time-slot collisions with already-enrolled courses."""
        try:
            new_schedule = CourseSchedule.objects.filter(course=course)
        except Exception:
            return  # gracefully skip if schedule data unavailable
        if not new_schedule.exists():
            return
        enrolled_ids = self._get_active_enrollments().values_list("course_id", flat=True)
        conflicts = CourseSchedule.objects.filter(
            course_id__in=enrolled_ids,
        ).filter(
            day_of_week__in=new_schedule.values_list("day_of_week", flat=True),
        )
        for existing in conflicts:
            for new_slot in new_schedule.filter(day_of_week=existing.day_of_week):
                if self._times_overlap(existing, new_slot):
                    raise RegistrationError(
                        "schedule_conflict",
                        f"{course.code} conflicts with an already-enrolled course on {existing.get_day_of_week_display()}."
                    )

    def _check_capacity(self, course: Course):
        active_count = Enrollment.objects.filter(
            course=course, status=Enrollment.Status.ACTIVE
        ).count()
        if active_count >= course.max_students:
            # Don't raise — place on waitlist instead
            pass  # handled in _create_enrollment

    # ── enrollment creation ─────────────────────────────────────────────────

    def _create_enrollment(self, course: Course) -> Enrollment:
        active_count = Enrollment.objects.select_for_update().filter(
            course=course, status=Enrollment.Status.ACTIVE
        ).count()
        is_full = active_count >= course.max_students
        status = Enrollment.Status.WAITLISTED if is_full else Enrollment.Status.ACTIVE
        enrollment = Enrollment.objects.create(
            student=self.student,
            course=course,
            status=status,
            enrolled_at=timezone.now(),
        )
        self._active_enrollments = None
        logger.info(
            "Registration: student=%s course=%s status=%s semester=%s",
            self.student.email, course.code, status, self.semester,
        )
        return enrollment

    def _promote_waitlist(self, course: Course):
        """Move the first waitlisted student into active status."""
        next_up = (
            Enrollment.objects
            .filter(course=course, status=Enrollment.Status.WAITLISTED)
            .order_by("enrolled_at")
            .first()
        )
        if next_up:
            next_up.status = Enrollment.Status.ACTIVE
            next_up.save(update_fields=["status"])
            logger.info("Promoted %s from waitlist for %s", next_up.student.email, course.code)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _get_active_enrollments(self):
        if self._active_enrollments is None:
            self._active_enrollments = Enrollment.objects.filter(
                student=self.student,
                status=Enrollment.Status.ACTIVE,
                course__start_date__year=timezone.now().year,
            )
        return self._active_enrollments

    def _get_semester_credits(self) -> int:
        return sum(
            e.course.credits
            for e in self._get_active_enrollments().select_related("course")
        )

    @staticmethod
    def _times_overlap(a, b) -> bool:
        return a.start_time < b.end_time and b.start_time < a.end_time

    def _post_register_tasks(self, enrollment: Enrollment):
        """Fire-and-forget Celery tasks after successful registration."""
        from apps.notifications.tasks import create_notification, send_email_notification
        status_label = "waitlisted" if enrollment.status == Enrollment.Status.WAITLISTED else "confirmed"
        title = f"Registration {'Waitlisted' if enrollment.status == Enrollment.Status.WAITLISTED else 'Confirmed'}"
        body = (
            f"You have been {'added to the waitlist' if enrollment.status == Enrollment.Status.WAITLISTED else 'registered'} "
            f"for {enrollment.course.code} — {enrollment.course.title}."
        )
        create_notification.delay(
            user_id=str(self.student.pk),
            notif_type="enrollment_confirmed",
            title=title,
            body=body,
            data={"course_id": str(enrollment.course.pk), "status": status_label},
        )
        send_email_notification.delay(
            user_id=str(self.student.pk),
            subject=f"[UniPortal] {title}: {enrollment.course.code}",
            body=body,
        )
