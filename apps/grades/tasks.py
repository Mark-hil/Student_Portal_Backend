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
