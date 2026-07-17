"""
GPA computation engine.
Semester GPA  = Σ(grade_points × credits) / Σ(credits)  — one term
Cumulative GPA = Σ(grade_points × credits) / Σ(credits)  — all completed terms

Called by: GradeBatch.publish() → recompute_gpa_for_student (Celery)
"""
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone

from .models import SemesterRecord, Transcript, GRADE_POINTS, letter_from_pct

TWO = Decimal("0.01")
_r  = lambda v: v.quantize(TWO, rounding=ROUND_HALF_UP)


def compute_course_final_grade(student, course) -> dict:
    """Weighted final grade for one course from published grades only."""
    from .models import Grade
    grades = (
        Grade.objects
        .filter(student=student, assignment__course=course, score__isnull=False, is_published=True)
        .select_related("assignment")
    )
    if not grades.exists():
        return {"letter": None, "grade_points": None, "percentage": None}

    total_weight = Decimal("0")
    weighted     = Decimal("0")
    for g in grades:
        w        = g.assignment.weight / Decimal("100")
        pct      = (g.score / g.assignment.max_score) * 100
        weighted += pct * w
        total_weight += w

    if total_weight == 0:
        return {"letter": None, "grade_points": None, "percentage": None}

    pct    = float(weighted / total_weight)
    letter = letter_from_pct(pct)
    return {"letter": letter, "grade_points": GRADE_POINTS.get(letter), "percentage": round(pct, 2)}


def compute_semester_gpa(student, semester: str):
    rows = Transcript.objects.filter(student=student, semester=semester, grade_points__isnull=False)
    cr   = sum(r.credits_attempted for r in rows)
    qp   = sum(r.quality_points for r in rows if r.quality_points)
    return _r(Decimal(str(qp)) / Decimal(str(cr))) if cr else None


def compute_cumulative_gpa(student):
    rows = Transcript.objects.filter(student=student, grade_points__isnull=False, credits_attempted__gt=0)
    cr   = sum(r.credits_attempted for r in rows)
    qp   = sum(r.quality_points for r in rows if r.quality_points)
    return _r(Decimal(str(qp)) / Decimal(str(cr))) if cr else None


@transaction.atomic
def recompute_student_gpas(student, semester: str, semester_label: str) -> dict:
    from apps.courses.models import Enrollment

    # 1. Update transcript rows for this semester
    for enr in Enrollment.objects.filter(student=student, course__semester=semester, status__in=["active","completed"]).select_related("course"):
        res = compute_course_final_grade(student, enr.course)
        if res["letter"] is None:
            continue
        qp = (res["grade_points"] or Decimal("0")) * Decimal(str(enr.course.credits))
        Transcript.objects.update_or_create(
            student=student, course=enr.course, semester=semester,
            defaults={
                "semester_label":  semester_label,
                "final_grade":     res["letter"],
                "grade_points":    res["grade_points"],
                "credits_attempted": enr.course.credits,
                "credits_earned":  enr.course.credits if res["letter"] != "F" else 0,
                "quality_points":  _r(qp),
                "computed_at":     timezone.now(),
            }
        )

    # 2. Compute GPA values
    sem_gpa = compute_semester_gpa(student, semester)
    cum_gpa = compute_cumulative_gpa(student)

    # 3. Aggregate for SemesterRecord
    sem_rows = Transcript.objects.filter(student=student, semester=semester)
    all_rows = Transcript.objects.filter(student=student)

    sem_cr = sum(r.credits_attempted for r in sem_rows)
    sem_ce = sum(r.credits_earned    for r in sem_rows)
    sem_qp = sum(r.quality_points    for r in sem_rows if r.quality_points)
    cum_cr = sum(r.credits_attempted for r in all_rows)
    cum_ce = sum(r.credits_earned    for r in all_rows)
    cum_qp = sum(r.quality_points    for r in all_rows if r.quality_points)

    SemesterRecord.objects.update_or_create(
        student=student, semester=semester,
        defaults={
            "semester_label":              semester_label,
            "semester_gpa":               sem_gpa,
            "semester_credits_attempted": sem_cr,
            "semester_credits_earned":    sem_ce,
            "semester_quality_points":    _r(Decimal(str(sem_qp))),
            "cumulative_gpa":             cum_gpa,
            "cumulative_credits_attempted": cum_cr,
            "cumulative_credits_earned":  cum_ce,
            "cumulative_quality_points":  _r(Decimal(str(cum_qp))),
            "computed_at":                timezone.now(),
        }
    )

    # 4. Update profile
    try:
        p = student.profile
        p.gpa = cum_gpa
        p.total_credits = cum_ce
        p.save(update_fields=["gpa", "total_credits"])
    except Exception:
        pass

    return {"semester_gpa": sem_gpa, "cumulative_gpa": cum_gpa}
