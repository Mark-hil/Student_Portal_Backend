import pytest
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.courses.models import Course, Enrollment
from apps.grades.models import Assignment, Grade, GradeBatch, GradeAppeal, SemesterRecord
from apps.users.models import AuditLog, AcademicProgressionLog
from apps.grades.tasks import evaluate_semester_academic_standing

User = get_user_model()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def student(db):
    return User.objects.create_user(
        email="appeal_student@uniportal.edu",
        password="password123",
        role="student",
        first_name="Alice",
        last_name="Smith",
        student_id="STU2025099",
        is_registered=True,
    )


@pytest.fixture
def student_two(db):
    return User.objects.create_user(
        email="other_student@uniportal.edu",
        password="password123",
        role="student",
        first_name="Bob",
        last_name="Jones",
        student_id="STU2025100",
        is_registered=True,
    )


@pytest.fixture
def lecturer(db):
    return User.objects.create_user(
        email="appeal_lecturer@uniportal.edu",
        password="password123",
        role="instructor",
        first_name="Ada",
        last_name="Lovelace",
    )


@pytest.fixture
def officer(db):
    return User.objects.create_user(
        email="appeal_officer@uniportal.edu",
        password="password123",
        role="staff",
        first_name="Margaret",
        last_name="Hamilton",
        is_staff=True,
    )


@pytest.fixture
def course(db, lecturer):
    c = Course.objects.create(
        code="NUR102",
        slug="nur102",
        title="Anatomy & Physiology",
        credits=3,
        max_students=40,
        semester="2025-SPRING",
        status="active",
    )
    c.instructors.add(lecturer)
    return c


@pytest.fixture
def published_grade(db, course, student, lecturer):
    assignment = Assignment.objects.create(
        course=course,
        title="Midterm Examination",
        assignment_type="midterm",
        max_score=100,
        weight=30,
        is_published=True,
    )
    return Grade.objects.create(
        student=student,
        assignment=assignment,
        score=Decimal("45.00"),
        is_published=True,
        graded_by=lecturer,
    )


@pytest.mark.django_db
def test_grade_appeal_submission_by_student(client, student, published_grade):
    client.force_authenticate(user=student)
    url = "/api/v1/grades/appeals/"
    data = {
        "grade": str(published_grade.id),
        "suggested_score": "75.00",
        "reason": "Midterm Section B marks were omitted during computation.",
    }
    res = client.post(url, data, format="json")
    assert res.status_code == 201, res.data
    appeal = GradeAppeal.objects.get(id=res.data["id"])
    assert appeal.student == student
    assert appeal.original_score == Decimal("45.00")
    assert appeal.suggested_score == Decimal("75.00")
    assert appeal.status == GradeAppeal.Status.PENDING
    assert appeal.course == published_grade.assignment.course


@pytest.mark.django_db
def test_student_cannot_appeal_other_student_grade(client, student_two, published_grade):
    client.force_authenticate(user=student_two)
    url = "/api/v1/grades/appeals/"
    data = {
        "grade": str(published_grade.id),
        "suggested_score": "80.00",
        "reason": "Trying to appeal someone else's grade.",
    }
    res = client.post(url, data, format="json")
    assert res.status_code == 400


@pytest.mark.django_db
def test_grade_appeal_hod_endorsement(client, lecturer, student, published_grade):
    appeal = GradeAppeal.objects.create(
        grade=published_grade,
        student=student,
        course=published_grade.assignment.course,
        original_score=Decimal("45.00"),
        suggested_score=Decimal("75.00"),
        reason="Computation error verified by class rep.",
    )
    client.force_authenticate(user=lecturer)
    url = f"/api/v1/grades/appeals/{appeal.id}/endorse/"
    res = client.post(url, {"comment": "Verified Section B question 4 was unmarked."}, format="json")
    assert res.status_code == 200, res.data
    appeal.refresh_from_db()
    assert appeal.status == GradeAppeal.Status.HOD_APPROVED
    assert "Verified Section B" in appeal.hod_comment


@pytest.mark.django_db
@patch("apps.grades.tasks.recompute_gpa_for_student.delay")
def test_grade_appeal_approval_and_audit_logging(mock_gpa_delay, client, officer, student, published_grade):
    appeal = GradeAppeal.objects.create(
        grade=published_grade,
        student=student,
        course=published_grade.assignment.course,
        original_score=Decimal("45.00"),
        suggested_score=Decimal("75.00"),
        reason="Omitted marks.",
    )
    client.force_authenticate(user=officer)
    url = f"/api/v1/grades/appeals/{appeal.id}/approve/"
    res = client.post(url, {"final_score": "78.00", "notes": "Approved per faculty board review."}, format="json")
    assert res.status_code == 200, res.data

    appeal.refresh_from_db()
    published_grade.refresh_from_db()
    assert appeal.status == GradeAppeal.Status.APPROVED
    assert appeal.final_score == Decimal("78.00")
    assert published_grade.score == Decimal("78.00")
    assert mock_gpa_delay.called

    # Check AuditLog
    audit_entry = AuditLog.objects.filter(action="grade_appeal_approved", target_id=str(appeal.id)).first()
    assert audit_entry is not None
    assert audit_entry.actor == officer
    assert audit_entry.changes["score"]["new"] == 78.0


@pytest.mark.django_db
def test_grade_appeal_rejection(client, officer, student, published_grade):
    appeal = GradeAppeal.objects.create(
        grade=published_grade,
        student=student,
        course=published_grade.assignment.course,
        original_score=Decimal("45.00"),
        suggested_score=Decimal("90.00"),
        reason="Unreasonable jump requested without evidence.",
    )
    client.force_authenticate(user=officer)
    url = f"/api/v1/grades/appeals/{appeal.id}/reject/"
    res = client.post(url, {"notes": "Original script reviewed. Marking was accurate."}, format="json")
    assert res.status_code == 200, res.data

    appeal.refresh_from_db()
    published_grade.refresh_from_db()
    assert appeal.status == GradeAppeal.Status.REJECTED
    assert published_grade.score == Decimal("45.00")  # Score untouched

    audit_entry = AuditLog.objects.filter(action="grade_appeal_rejected", target_id=str(appeal.id)).first()
    assert audit_entry is not None


@pytest.mark.django_db
@patch("apps.notifications.tasks.create_notification.delay")
@patch("apps.notifications.tasks.send_email_notification.delay")
def test_evaluate_academic_standing_probation_and_recovery(mock_email, mock_notif, student):
    # Setup initial record with low CGPA < 1.50
    SemesterRecord.objects.create(
        student=student,
        semester="2025-SPRING",
        semester_label="Spring 2025",
        cumulative_gpa=Decimal("1.25"),
        status="completed",
    )

    # Run standing evaluation task
    result = evaluate_semester_academic_standing(semester="2025-SPRING", probation_threshold=1.5)
    student.refresh_from_db()

    assert result["probation_count"] == 1
    assert student.academic_status == User.AcademicStatus.PROBATION

    # Check progression log
    prog_log = AcademicProgressionLog.objects.filter(student=student).first()
    assert prog_log is not None
    assert prog_log.to_status == User.AcademicStatus.PROBATION

    # Check audit log
    audit = AuditLog.objects.filter(action="student_probation_placed", target_id=str(student.id)).first()
    assert audit is not None

    # Now simulate recovery next semester: CGPA rises to 2.20
    rec = SemesterRecord.objects.get(student=student, semester="2025-SPRING")
    rec.cumulative_gpa = Decimal("2.20")
    rec.save()

    result_recovery = evaluate_semester_academic_standing(semester="2025-SPRING", probation_threshold=1.5, good_standing_threshold=1.5)
    student.refresh_from_db()

    assert result_recovery["cleared_count"] == 1
    assert student.academic_status == User.AcademicStatus.ACTIVE

    # Check cleared audit log
    audit_cleared = AuditLog.objects.filter(action="student_probation_cleared", target_id=str(student.id)).first()
    assert audit_cleared is not None
