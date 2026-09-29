"""Celery tasks for GPA recomputation."""
import logging
from celery import shared_task
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def recompute_gpa_for_student(self, student_id: str, semester: str, semester_label: str):
    from .gpa import recompute_student_gpas
    try:
        student = User.objects.get(id=student_id)
        result  = recompute_student_gpas(student, semester, semester_label)
        logger.info("GPA recomputed: student=%s semester=%s → sem=%s cum=%s",
            student.email, semester, result["semester_gpa"], result["cumulative_gpa"])
        return result
    except User.DoesNotExist:
        logger.error("recompute_gpa: student %s not found", student_id)
    except Exception as exc:
        logger.exception("recompute_gpa failed for %s", student_id)
        raise self.retry(exc=exc)


@shared_task
def bulk_recompute_all_gpas():
    """Nightly task — recompute GPAs for all active students."""
    from apps.courses.models import Enrollment
    from .gpa import recompute_student_gpas
    pairs = (
        Enrollment.objects.filter(status="active")
        .select_related("student", "course")
        .values_list("student_id", "course__semester")
        .distinct()
    )
    count = 0
    for student_id, semester in pairs:
        if not semester:
            continue
        try:
            student = User.objects.get(id=student_id)
            recompute_student_gpas(student, semester, semester)
            count += 1
        except Exception:
            pass
    logger.info("bulk_recompute_all_gpas: processed %d pairs", count)
    return count


@shared_task
def evaluate_semester_academic_standing(
    semester: str = None,
    academic_year: str = None,
    probation_threshold: float = 1.5,
    good_standing_threshold: float = 1.5,
):
    """
    Evaluates cumulative GPA at the end of a semester for all active students.
    Institutional Rules:
    - If CGPA < probation_threshold (default 1.50):
      Student is placed on PROBATION.
      Logged to AcademicProgressionLog and immutable AuditLog.
      Dispatches student alert notification and email.
    - If student is currently on PROBATION and CGPA >= good_standing_threshold:
      Student is restored to ACTIVE good standing.
      Logged to AcademicProgressionLog and immutable AuditLog.
      Dispatches student notification and email.
    """
    from decimal import Decimal
    from apps.users.models import AcademicProgressionLog, AuditLog
    from apps.users.services.audit_service import AuditService
    from apps.notifications.tasks import create_notification, send_email_notification
    from .models import SemesterRecord
    from .gpa import compute_cumulative_gpa

    threshold_decimal = Decimal(str(probation_threshold))
    good_standing_decimal = Decimal(str(good_standing_threshold))

    students = User.objects.filter(
        role=User.Role.STUDENT,
        is_active=True,
    ).exclude(
        academic_status__in=[
            User.AcademicStatus.GRADUATED,
            User.AcademicStatus.WITHDRAWN,
            User.AcademicStatus.DELETED,
        ]
    )

    evaluated_count = 0
    probation_count = 0
    cleared_count = 0

    for student in students:
        cgpa = None
        if semester:
            rec = SemesterRecord.objects.filter(student=student, semester=semester).first()
            if rec and rec.cumulative_gpa is not None:
                cgpa = rec.cumulative_gpa
        if cgpa is None:
            latest_rec = SemesterRecord.objects.filter(student=student).order_by("-computed_at").first()
            if latest_rec and latest_rec.cumulative_gpa is not None:
                cgpa = latest_rec.cumulative_gpa
            else:
                cgpa = compute_cumulative_gpa(student)

        if cgpa is None:
            continue

        evaluated_count += 1
        cgpa_val = Decimal(str(cgpa))

        # Check for probation condition
        if cgpa_val < threshold_decimal:
            if student.academic_status != User.AcademicStatus.PROBATION:
                old_status = student.academic_status
                student.academic_status = User.AcademicStatus.PROBATION
                student.save(update_fields=["academic_status"])
                probation_count += 1

                # 1. Progression Log
                AcademicProgressionLog.objects.create(
                    student=student,
                    action=AcademicProgressionLog.ActionType.STATUS_CHANGE,
                    from_level=student.class_name,
                    to_level=student.class_name,
                    from_status=old_status,
                    to_status=User.AcademicStatus.PROBATION,
                    reason=f"End-of-term CGPA of {cgpa_val:.2f} fell below minimum required threshold of {probation_threshold:.2f}.",
                    academic_year=academic_year or "",
                    semester=semester or "",
                    metadata={"cumulative_gpa": float(cgpa_val), "threshold": probation_threshold},
                )

                # 2. Immutable Audit Log
                AuditService.log_event(
                    action="student_probation_placed",
                    category=AuditLog.Category.ACADEMICS,
                    actor=None,
                    actor_email="system@celery",
                    actor_role="system",
                    status=AuditLog.Status.SUCCESS,
                    target_type="User",
                    target_id=str(student.id),
                    target_repr=student.email,
                    description=f"Student placed on Academic Probation due to CGPA {cgpa_val:.2f} < {probation_threshold:.2f}.",
                    changes={"academic_status": {"old": old_status, "new": User.AcademicStatus.PROBATION}},
                    metadata={"cumulative_gpa": float(cgpa_val), "semester": semester, "threshold": probation_threshold},
                )

                # 3. Notifications
                body = (
                    f"Your end-of-term cumulative GPA of {cgpa_val:.2f} has fallen below the minimum "
                    f"academic requirement ({probation_threshold:.2f}). You have been placed on Academic Probation. "
                    "Please contact your Academic Advisor or Head of Department for counseling."
                )
                create_notification.delay(
                    user_id=str(student.id),
                    notif_type="academic_probation_placed",
                    title="Academic Alert: Placed on Academic Probation",
                    body=body,
                    data={"cgpa": str(cgpa_val), "semester": semester or "", "status": "probation"},
                )
                send_email_notification.delay(
                    user_id=str(student.id),
                    subject="[UniPortal] Academic Notice: Academic Probation",
                    body=body,
                )

        # Check for recovery from probation
        elif student.academic_status == User.AcademicStatus.PROBATION and cgpa_val >= good_standing_decimal:
            old_status = student.academic_status
            student.academic_status = User.AcademicStatus.ACTIVE
            student.save(update_fields=["academic_status"])
            cleared_count += 1

            AcademicProgressionLog.objects.create(
                student=student,
                action=AcademicProgressionLog.ActionType.STATUS_CHANGE,
                from_level=student.class_name,
                to_level=student.class_name,
                from_status=old_status,
                to_status=User.AcademicStatus.ACTIVE,
                reason=f"Restored to Good Academic Standing with CGPA of {cgpa_val:.2f} meeting threshold {good_standing_threshold:.2f}.",
                academic_year=academic_year or "",
                semester=semester or "",
                metadata={"cumulative_gpa": float(cgpa_val), "threshold": good_standing_threshold},
            )

            AuditService.log_event(
                action="student_probation_cleared",
                category=AuditLog.Category.ACADEMICS,
                actor=None,
                actor_email="system@celery",
                actor_role="system",
                status=AuditLog.Status.SUCCESS,
                target_type="User",
                target_id=str(student.id),
                target_repr=student.email,
                description=f"Student cleared from Academic Probation with CGPA {cgpa_val:.2f} >= {good_standing_threshold:.2f}.",
                changes={"academic_status": {"old": old_status, "new": User.AcademicStatus.ACTIVE}},
                metadata={"cumulative_gpa": float(cgpa_val), "semester": semester},
            )

            body = (
                f"Congratulations! Your cumulative GPA of {cgpa_val:.2f} satisfies the institutional "
                f"academic standard. You have been restored to Good Academic Standing."
            )
            create_notification.delay(
                user_id=str(student.id),
                notif_type="academic_probation_cleared",
                title="Academic Notice: Restored to Good Standing",
                body=body,
                data={"cgpa": str(cgpa_val), "semester": semester or "", "status": "active"},
            )
            send_email_notification.delay(
                user_id=str(student.id),
                subject="[UniPortal] Academic Notice: Restored to Good Standing",
                body=body,
            )

    logger.info(
        "evaluate_semester_academic_standing: evaluated=%d placed_on_probation=%d cleared_from_probation=%d semester=%s",
        evaluated_count, probation_count, cleared_count, semester
    )
    return {
        "evaluated_count": evaluated_count,
        "probation_count": probation_count,
        "cleared_count": cleared_count,
        "semester": semester,
    }

