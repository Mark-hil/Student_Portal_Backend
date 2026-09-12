import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.financials.models import StudentAccountStatement, Payment
from apps.courses.models import Course, Enrollment
from apps.grades.models import Assignment, Submission

User = get_user_model()

@pytest.fixture
def client():
    return APIClient()

@pytest.fixture
def student_user(db):
    return User.objects.create_user(
        email="stu_export@uniportal.edu",
        password="password123",
        role=User.Role.STUDENT,
        first_name="Export",
        last_name="Student",
        student_id="STU-EXP-001"
    )

@pytest.fixture
def finance_user(db):
    return User.objects.create_user(
        email="fin_export@uniportal.edu",
        password="password123",
        role="finance",
        first_name="Finance",
        last_name="Officer"
    )

@pytest.fixture
def lecturer_user(db):
    return User.objects.create_user(
        email="lec_export@uniportal.edu",
        password="password123",
        role=User.Role.INSTRUCTOR,
        first_name="Lecturer",
        last_name="Professor"
    )

@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin_export@uniportal.edu",
        password="password123",
        role=User.Role.ADMIN,
        first_name="Admin",
        last_name="Manager"
    )

@pytest.mark.django_db
def test_finance_exports(client, finance_user, student_user):
    client.force_authenticate(user=finance_user)

    # Seed statement and payment
    stmt = StudentAccountStatement.objects.create(
        student=student_user,
        semester="Spring 2026",
        academic_level="200",
        academic_fee=Decimal("3850.00"),
        ict_library_fee=Decimal("350.00"),
        src_dues=Decimal("180.00"),
        examination_fee=Decimal("220.00"),
        total_billed=Decimal("4600.00"),
        total_paid=Decimal("2000.00"),
        balance=Decimal("2600.00"),
    )
    Payment.objects.create(
        student=student_user,
        statement=stmt,
        amount=Decimal("2000.00"),
        channel=Payment.Channel.MOMO,
        provider="MTN",
        reference_number="MOMO-EXP-999",
        status=Payment.Status.COMPLETED
    )

    # 1. Export statements
    res = client.get("/api/v1/financials/admin/export/statements/")
    assert res.status_code == 200
    assert "text/csv" in res["Content-Type"]
    content = res.content.decode("utf-8-sig")
    assert "STU-EXP-001" in content
    assert "3850.00" in content
    assert "2600.00" in content

    # 2. Export payments
    res = client.get("/api/v1/financials/admin/export/payments/")
    assert res.status_code == 200
    assert "text/csv" in res["Content-Type"]
    content = res.content.decode("utf-8-sig")
    assert "MOMO-EXP-999" in content
    assert "2000.00" in content

@pytest.mark.django_db
def test_student_statement_export(client, student_user):
    client.force_authenticate(user=student_user)
    StudentAccountStatement.objects.create(
        student=student_user,
        semester="Spring 2026",
        academic_level="100",
        total_billed=Decimal("4600.00"),
        total_paid=Decimal("4600.00"),
        balance=Decimal("0.00")
    )
    res = client.get("/api/v1/financials/statement/export-csv/")
    assert res.status_code == 200
    assert "text/csv" in res["Content-Type"]
    content = res.content.decode("utf-8-sig")
    assert "OFFICIAL STUDENT STATEMENT OF ACCOUNT" in content
    assert "STU-EXP-001" in content

@pytest.mark.django_db
def test_lecturer_course_exports(client, lecturer_user, student_user):
    course = Course.objects.create(
        code="CS401",
        title="Distributed Systems",
        credits=3,
        semester="Spring 2026",
        max_students=50
    )
    course.instructors.add(lecturer_user)
    Enrollment.objects.create(student=student_user, course=course, status=Enrollment.Status.ACTIVE)

    assignment = Assignment.objects.create(
        course=course,
        title="Lab 1: Consensus",
        max_score=Decimal("100.00"),
        weight=Decimal("20.00")
    )
    Submission.objects.create(
        assignment=assignment,
        student=student_user,
        score=Decimal("95.00")
    )

    client.force_authenticate(user=lecturer_user)

    # 1. Export Roster
    res = client.get(f"/api/v1/courses/{course.id}/export-roster/")
    assert res.status_code == 200
    assert "text/csv" in res["Content-Type"]
    content = res.content.decode("utf-8-sig")
    assert "STU-EXP-001" in content
    assert "CS401" in content

    # 2. Export Grades
    res = client.get(f"/api/v1/courses/{course.id}/export-grades/")
    assert res.status_code == 200
    assert "text/csv" in res["Content-Type"]
    content = res.content.decode("utf-8-sig")
    assert "Lab 1: Consensus" in content
    assert "95.0" in content

@pytest.mark.django_db
def test_admin_export_students(client, admin_user, student_user):
    client.force_authenticate(user=admin_user)
    res = client.get("/api/v1/users/export-students/")
    assert res.status_code == 200
    assert "text/csv" in res["Content-Type"]
    content = res.content.decode("utf-8-sig")
    assert "INSTITUTIONAL STUDENT DIRECTORY" in content
    assert "STU-EXP-001" in content
