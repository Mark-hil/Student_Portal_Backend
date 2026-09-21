"""
Student Academic Progression & Lifecycle Service.
Handles student promotions, demotions, withdrawals, reinstatements,
soft deletions, restores, and guarded permanent deletions with full audit logging.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from apps.users.models import AcademicProgressionLog, UserProfile

logger = logging.getLogger(__name__)
User = get_user_model()

# Standard academic level progression sequence for college programs
LEVEL_SEQUENCE = ["100", "200", "300", "400"]
MAX_DIPLOMA_LEVEL = "300"  # Nursing and Midwifery 3-year Diploma programs complete at Level 300


def get_next_level(current_level: str, program: str = "nursing") -> Tuple[Optional[str], bool]:
    """
    Returns (next_level, is_graduating).
    If currently at or above max level, is_graduating is True.
    """
    clean_level = str(current_level).strip()
    if clean_level not in LEVEL_SEQUENCE:
        clean_level = "100"

    current_idx = LEVEL_SEQUENCE.index(clean_level)

    # For 3-year diploma programs, Level 300 is the graduating class
    is_diploma = str(program).lower() in ("nursing", "midwifery", "diploma")
    max_level_for_prog = MAX_DIPLOMA_LEVEL if is_diploma else "400"

    if clean_level == max_level_for_prog or current_idx >= LEVEL_SEQUENCE.index(max_level_for_prog):
        return None, True  # Ready to graduate

    next_level = LEVEL_SEQUENCE[current_idx + 1]
    return next_level, False


def get_previous_level(current_level: str) -> str:
    """Returns the preceding academic level or '100'."""
    clean_level = str(current_level).strip()
    if clean_level not in LEVEL_SEQUENCE or clean_level == "100":
        return "100"
    current_idx = LEVEL_SEQUENCE.index(clean_level)
    return LEVEL_SEQUENCE[max(0, current_idx - 1)]


def _sync_student_level(student, new_level: str):
    """Synchronize class_name on User and academic_level on UserProfile."""
    student.class_name = new_level
    student.save(update_fields=["class_name"])

    profile, _ = UserProfile.objects.get_or_create(user=student)
    profile.academic_level = new_level
    profile.save(update_fields=["academic_level"])


def _extract_student_academic_snapshot(student) -> Dict[str, Any]:
    """Capture GPA and credit metrics at time of transition."""
    snapshot = {
        "current_gpa": None,
        "total_credits": 0,
        "program": student.program,
        "email": student.email,
        "student_id": student.student_id,
    }
    try:
        latest_rec = student.semester_records.order_by("-computed_at").first()
        if latest_rec and latest_rec.cumulative_gpa is not None:
            snapshot["current_gpa"] = float(latest_rec.cumulative_gpa)
            snapshot["total_credits"] = int(latest_rec.cumulative_credits_earned)
    except Exception as e:
        logger.debug("Could not fetch semester records for snapshot: %s", e)
    return snapshot


@transaction.atomic
def promote_student(
    student,
    target_level: Optional[str] = None,
    academic_year: str = "",
    semester: str = "",
    notes: str = "",
    actor=None,
) -> Dict[str, Any]:
    """
    Promote a student to the next academic level or graduate them if at final year.
    """
    if student.role != User.Role.STUDENT:
        raise ValidationError("Only accounts with role 'student' can undergo academic promotion.")

    if student.deleted_at is not None or student.academic_status == User.AcademicStatus.DELETED:
        raise ValidationError("Cannot promote an archived / deleted student account. Restore first.")

    current_level = student.class_name or (student.profile.academic_level if hasattr(student, "profile") else "100")
    old_status = student.academic_status

    if target_level:
        new_level = str(target_level).strip()
        is_graduating = new_level.lower() in ("graduated", "alumni")
    else:
        computed_next, is_graduating = get_next_level(current_level, student.program)
        new_level = computed_next or current_level

    snapshot = _extract_student_academic_snapshot(student)

    if is_graduating:
        student.academic_status = User.AcademicStatus.GRADUATED
        student.graduation_date = timezone.now().date()
        student.is_active = True
        student.save(update_fields=["academic_status", "graduation_date", "is_active"])
        new_level = "Graduated"
        action_type = AcademicProgressionLog.ActionType.GRADUATION
        message = f"Student {student.full_name} ({student.student_id or student.email}) has successfully graduated!"
    else:
        student.academic_status = User.AcademicStatus.ACTIVE
        student.save(update_fields=["academic_status"])
        _sync_student_level(student, new_level)
        action_type = AcademicProgressionLog.ActionType.PROMOTION
        message = f"Student {student.full_name} promoted from Level {current_level} to Level {new_level}."

    log_entry = AcademicProgressionLog.objects.create(
        student=student,
        action=action_type,
        from_level=current_level,
        to_level=new_level,
        from_status=old_status,
        to_status=student.academic_status,
        reason=notes or f"Promoted to Level {new_level}",
        academic_year=academic_year,
        semester=semester,
        performed_by=actor,
        metadata=snapshot,
    )

    # Optional: trigger notification task
    try:
        from apps.notifications.tasks import create_notification
        notif_title = "Academic Graduation" if is_graduating else "Academic Level Promotion"
        create_notification.delay(
            user_id=str(student.id),
            notif_type="academic_update",
            title=notif_title,
            body=(
                f"Congratulations! You have been officially transitioned to {new_level} "
                f"for academic session {academic_year or 'Current'}."
            ),
            data={"log_id": str(log_entry.id), "level": new_level},
        )
    except Exception as e:
        logger.debug("Notification task dispatch skipped: %s", e)

    return {
        "success": True,
        "message": message,
        "student_id": student.student_id,
        "from_level": current_level,
        "to_level": new_level,
        "academic_status": student.academic_status,
        "log_id": str(log_entry.id),
    }


@transaction.atomic
def demote_student(
    student,
    target_level: Optional[str] = None,
    reason: str = "",
    academic_year: str = "",
    semester: str = "",
    notes: str = "",
    actor=None,
) -> Dict[str, Any]:
    """
    Demote or retain a student to repeat a level due to academic or disciplinary sanction.
    Reason is mandatory.
    """
    if student.role != User.Role.STUDENT:
        raise ValidationError("Only student accounts can undergo academic demotion / retention.")

    if not reason or not reason.strip():
        raise ValidationError("An explicit administrative or academic reason is required for demotion / retention.")

    current_level = student.class_name or (student.profile.academic_level if hasattr(student, "profile") else "100")
    old_status = student.academic_status

    if target_level:
        new_level = str(target_level).strip()
    else:
        new_level = get_previous_level(current_level)

    snapshot = _extract_student_academic_snapshot(student)

    # If repeating the same level or stepping back, mark as repeating
    student.academic_status = User.AcademicStatus.REPEATING
    student.save(update_fields=["academic_status"])
    _sync_student_level(student, new_level)

    log_entry = AcademicProgressionLog.objects.create(
        student=student,
        action=AcademicProgressionLog.ActionType.DEMOTION,
        from_level=current_level,
        to_level=new_level,
        from_status=old_status,
        to_status=student.academic_status,
        reason=f"{reason.strip()}. {notes.strip()}".strip(),
        academic_year=academic_year,
        semester=semester,
        performed_by=actor,
        metadata=snapshot,
    )

    try:
        from apps.notifications.tasks import create_notification
        create_notification.delay(
            user_id=str(student.id),
            notif_type="academic_update",
            title="Academic Standing & Level Adjustment",
            body=(
                f"Notice: Your academic level has been adjusted to Level {new_level} (Repeating). "
                f"Reason: {reason.strip()}."
            ),
            data={"log_id": str(log_entry.id), "level": new_level},
        )
    except Exception as e:
        logger.debug("Notification task dispatch skipped: %s", e)

    return {
        "success": True,
        "message": f"Student {student.full_name} demoted/retained at Level {new_level}.",
        "student_id": student.student_id,
        "from_level": current_level,
        "to_level": new_level,
        "academic_status": student.academic_status,
        "log_id": str(log_entry.id),
    }


@transaction.atomic
def withdraw_student(
    student,
    reason: str = "",
    effective_date=None,
    academic_year: str = "",
    semester: str = "",
    notes: str = "",
    actor=None,
) -> Dict[str, Any]:
    """
    Formally withdraw a student from the institution.
    Drops current in-progress course enrollments with status 'DROPPED' and grade 'W',
    preserving past completed transcripts intact.
    """
    if student.role != User.Role.STUDENT:
        raise ValidationError("Only student accounts can be withdrawn.")

    if not reason or not reason.strip():
        raise ValidationError("A withdrawal reason is required.")

    current_level = student.class_name or "100"
    old_status = student.academic_status
    date_val = effective_date or timezone.now().date()

    student.academic_status = User.AcademicStatus.WITHDRAWN
    student.is_active = False
    student.withdrawal_date = date_val
    student.withdrawal_reason = f"{reason.strip()}. {notes.strip()}".strip()
    student.save(update_fields=["academic_status", "is_active", "withdrawal_date", "withdrawal_reason"])

    # Gracefully drop active enrollments so current term does not calculate as failure "F"
    dropped_count = 0
    try:
        from apps.courses.models import Enrollment
        active_enrollments = student.enrollments.filter(status=Enrollment.Status.ACTIVE)
        dropped_count = active_enrollments.count()
        active_enrollments.update(
            status=Enrollment.Status.DROPPED,
            dropped_at=timezone.now(),
            final_grade="W",
        )
    except Exception as e:
        logger.warning("Error updating active enrollments during withdrawal: %s", e)

    log_entry = AcademicProgressionLog.objects.create(
        student=student,
        action=AcademicProgressionLog.ActionType.WITHDRAWAL,
        from_level=current_level,
        to_level=current_level,
        from_status=old_status,
        to_status=User.AcademicStatus.WITHDRAWN,
        reason=student.withdrawal_reason,
        academic_year=academic_year,
        semester=semester,
        performed_by=actor,
        metadata={
            "effective_date": str(date_val),
            "dropped_courses_count": dropped_count,
        },
    )

    return {
        "success": True,
        "message": f"Student {student.full_name} has been formally withdrawn. {dropped_count} active course(s) dropped.",
        "student_id": student.student_id,
        "academic_status": student.academic_status,
        "dropped_courses_count": dropped_count,
        "log_id": str(log_entry.id),
    }


@transaction.atomic
def reinstate_student(
    student,
    target_level: Optional[str] = None,
    academic_year: str = "",
    semester: str = "",
    notes: str = "",
    actor=None,
) -> Dict[str, Any]:
    """
    Reinstate a withdrawn or suspended student back to active enrollment.
    """
    if student.role != User.Role.STUDENT:
        raise ValidationError("Only student accounts can be reinstated.")

    current_level = student.class_name or "100"
    new_level = target_level.strip() if target_level else current_level
    old_status = student.academic_status

    student.academic_status = User.AcademicStatus.ACTIVE
    student.is_active = True
    student.withdrawal_date = None
    student.withdrawal_reason = ""
    student.save(update_fields=["academic_status", "is_active", "withdrawal_date", "withdrawal_reason"])

    if new_level != current_level:
        _sync_student_level(student, new_level)

    log_entry = AcademicProgressionLog.objects.create(
        student=student,
        action=AcademicProgressionLog.ActionType.REINSTATEMENT,
        from_level=current_level,
        to_level=new_level,
        from_status=old_status,
        to_status=User.AcademicStatus.ACTIVE,
        reason=notes or "Reinstated to active enrollment",
        academic_year=academic_year,
        semester=semester,
        performed_by=actor,
        metadata={"reinstated_at": str(timezone.now())},
    )

    return {
        "success": True,
        "message": f"Student {student.full_name} has been reinstated to active enrollment at Level {new_level}.",
        "student_id": student.student_id,
        "academic_status": student.academic_status,
        "level": new_level,
        "log_id": str(log_entry.id),
    }


@transaction.atomic
def soft_delete_student(student, reason: str = "", actor=None) -> Dict[str, Any]:
    """
    Safe soft-delete / archive student to trash. Preserves all historic records.
    """
    current_level = student.class_name or "100"
    old_status = student.academic_status

    student.soft_delete()

    log_entry = AcademicProgressionLog.objects.create(
        student=student,
        action=AcademicProgressionLog.ActionType.SOFT_DELETE,
        from_level=current_level,
        to_level=current_level,
        from_status=old_status,
        to_status=User.AcademicStatus.DELETED,
        reason=reason or "Account soft-deleted / archived to trash",
        performed_by=actor,
    )

    return {
        "success": True,
        "message": f"Student account for {student.full_name} has been archived to trash.",
        "student_id": student.student_id,
        "log_id": str(log_entry.id),
    }


@transaction.atomic
def restore_student(student, actor=None) -> Dict[str, Any]:
    """
    Restore an archived / soft-deleted student back to active status.
    """
    current_level = student.class_name or "100"
    student.restore()

    log_entry = AcademicProgressionLog.objects.create(
        student=student,
        action=AcademicProgressionLog.ActionType.RESTORE,
        from_level=current_level,
        to_level=current_level,
        from_status=User.AcademicStatus.DELETED,
        to_status=User.AcademicStatus.ACTIVE,
        reason="Account restored from trash",
        performed_by=actor,
    )

    return {
        "success": True,
        "message": f"Student account for {student.full_name} has been successfully restored.",
        "student_id": student.student_id,
        "log_id": str(log_entry.id),
    }


def can_hard_delete_student(student) -> Tuple[bool, List[str]]:
    """
    Check if a student can safely be permanently purged from the database.
    Hard deletion is prohibited if student has financial payments or published transcripts.
    """
    blockers = []

    # Check payments
    try:
        from apps.financials.models import Payment
        payments_count = Payment.objects.filter(student=student).count()
        if payments_count > 0:
            blockers.append(f"{payments_count} recorded financial payment(s) / receipt(s)")
    except Exception as e:
        logger.debug("Could not verify payments: %s", e)

    # Check transcripts
    try:
        from apps.grades.models import Transcript
        transcripts_count = Transcript.objects.filter(student=student).count()
        if transcripts_count > 0:
            blockers.append(f"{transcripts_count} published academic transcript course record(s)")
    except Exception as e:
        logger.debug("Could not verify transcripts: %s", e)

    # Check published grades
    try:
        from apps.grades.models import Grade
        published_grades = Grade.objects.filter(student=student, is_published=True).count()
        if published_grades > 0:
            blockers.append(f"{published_grades} published official grade(s)")
    except Exception as e:
        logger.debug("Could not verify grades: %s", e)

    return len(blockers) == 0, blockers


@transaction.atomic
def hard_delete_student(student, force: bool = False, actor=None) -> Dict[str, Any]:
    """
    Permanently purge a student record from the database.
    Strictly guarded: will fail if the student has academic transcripts or financial payments
    unless force=True is explicitly supplied by a Superadmin.
    """
    can_delete, blockers = can_hard_delete_student(student)

    if not can_delete and not force:
        blockers_str = ", ".join(blockers)
        raise ValidationError(
            f"Cannot permanently delete student {student.full_name} ({student.student_id or student.email}) "
            f"because irreversible official records exist: {blockers_str}. "
            f"Please use Soft Delete (Archive to Trash) or Withdrawal instead."
        )

    student_email = student.email
    student_id_str = student.student_id or "N/A"
    full_name = student.full_name

    logger.warning(
        "PERMANENT HARD DELETE executed for student %s (%s) by actor %s (force=%s)",
        student_email, student_id_str, getattr(actor, "email", "system"), force
    )

    # Use default model delete (cascades related objects)
    student.delete()

    return {
        "success": True,
        "message": f"Student record for {full_name} ({student_id_str}) was permanently purged.",
        "purged_email": student_email,
        "purged_student_id": student_id_str,
    }


def bulk_promote_cohort(
    student_ids: List[str],
    target_level: Optional[str] = None,
    academic_year: str = "",
    notes: str = "",
    actor=None,
) -> Dict[str, Any]:
    """
    Bulk promote a batch of students atomically.
    """
    if not student_ids:
        raise ValidationError("No students specified for bulk promotion.")

    students = User.objects.filter(id__in=student_ids, role=User.Role.STUDENT)
    results = {"succeeded": [], "failed": [], "total": len(student_ids)}

    for s in students:
        try:
            with transaction.atomic():
                res = promote_student(
                    student=s,
                    target_level=target_level,
                    academic_year=academic_year,
                    notes=notes,
                    actor=actor,
                )
                results["succeeded"].append({
                    "id": str(s.id),
                    "name": s.full_name,
                    "student_id": s.student_id,
                    "from_level": res["from_level"],
                    "to_level": res["to_level"],
                    "status": res["academic_status"],
                })
        except Exception as e:
            logger.exception("Bulk promote failed for student %s: %s", s.id, e)
            results["failed"].append({
                "id": str(s.id),
                "name": s.full_name,
                "student_id": s.student_id,
                "error": str(e),
            })

    return results
