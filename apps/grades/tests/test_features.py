import pytest
import io
import csv
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from apps.courses.models import Course, Enrollment
from apps.grades.models import Assignment, Grade, GradeBatch, Submission, Transcript, SemesterRecord

User = get_user_model()

@pytest.fixture
def client():
    return APIClient()

@pytest.fixture
def student(db):
    return User.objects.create_user(
        email="student_test@uniportal.edu",
        password="password123",
        role="student",
        first_name="Jane",
        last_name="Doe",
        student_id="STU2025001",
        department="Computer Science",
    )

@pytest.fixture
def lecturer(db):
    return User.objects.create_user(
        email="lecturer_test@uniportal.edu",
        password="password123",
        role="instructor",
        first_name="Alan",
        last_name="Turing",
    )

@pytest.fixture
def officer(db):
    return User.objects.create_user(
        email="officer_test@uniportal.edu",
        password="password123",
        role="staff",
        first_name="Grace",
        last_name="Hopper",
    )

@pytest.fixture
def course(db, lecturer):
    c = Course.objects.create(
        code="CS201",
        slug="cs201",
        title="Data Structures",
        credits=4,
        max_students=30,
        semester="2025-SPRING",
        status="active",
    )
    c.instructors.add(lecturer)
    return c

@pytest.fixture
def enrollment(db, student, course):
    return Enrollment.objects.create(student=student, course=course, status="active")

@pytest.fixture
def assignment(db, course):
    return Assignment.objects.create(
        course=course,
        title="Project 1: Balanced Trees",
        assignment_type="project",
        max_score=100,
        weight=25,
        is_published=True,
    )

@pytest.fixture
def grade_batch(db, assignment, lecturer):
    return GradeBatch.objects.create(
        assignment=assignment,
        submitted_by=lecturer,
        status=GradeBatch.Status.DRAFT,
    )


@pytest.mark.django_db
class TestPDFTranscriptGenerator:
    def test_transcript_pdf_endpoint(self, client, student, course, enrollment):
        Transcript.objects.create(
            student=student,
            course=course,
            semester="2025-SPRING",
            semester_label="Spring 2025",
            final_grade="A",
            grade_points=Decimal("4.00"),
            credits_attempted=4,
            credits_earned=4,
            quality_points=Decimal("16.00"),
        )
        SemesterRecord.objects.create(
            student=student,
            semester="2025-SPRING",
            semester_label="Spring 2025",
            semester_gpa=Decimal("4.00"),
            cumulative_gpa=Decimal("4.00"),
            semester_credits_attempted=4,
            semester_credits_earned=4,
            cumulative_credits_attempted=4,
            cumulative_credits_earned=4,
        )

        client.force_authenticate(user=student)
        response = client.get("/api/v1/grades/transcript/pdf/")
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert b"%PDF-" in response.content[:10]
        assert len(response.content) > 1000


@pytest.mark.django_db
class TestAssignmentSubmissions:
    def test_student_submit_text_assignment(self, client, student, assignment, enrollment):
        client.force_authenticate(user=student)
        payload = {
            "text_content": "https://github.com/janedoe/trees-repo\nImplemented AVL and Red-Black tree algorithms."
        }
        res = client.post(f"/api/v1/grades/assignments/{assignment.id}/submit/", data=payload, format="json")
        assert res.status_code == 200
        assert res.data["status"] == "submitted"
        assert "AVL" in res.data["text_content"]

        # Check my_submission
        res_my = client.get(f"/api/v1/grades/assignments/{assignment.id}/my-submission/")
        assert res_my.status_code == 200
        assert res_my.data["student_name"] == "Jane Doe"

    def test_lecturer_views_submissions(self, client, lecturer, student, assignment, enrollment):
        Submission.objects.create(
            assignment=assignment,
            student=student,
            text_content="Submission notes",
            status=Submission.Status.SUBMITTED,
        )
        client.force_authenticate(user=lecturer)
        res = client.get(f"/api/v1/grades/assignments/{assignment.id}/submissions/")
        assert res.status_code == 200
        assert len(res.data) == 1
        assert res.data[0]["student_code"] == "STU2025001"


@pytest.mark.django_db
class TestCSVImportExport:
    def test_export_csv_roster(self, client, lecturer, student, grade_batch, enrollment):
        client.force_authenticate(user=lecturer)
        res = client.get(f"/api/v1/grades/batches/{grade_batch.id}/export-csv/")
        assert res.status_code == 200
        assert res["Content-Type"] == "text/csv"
        content = res.content.decode("utf-8")
        assert "student_id,student_name,email,score,feedback" in content
        assert "STU2025001" in content
        assert "student_test@uniportal.edu" in content

    def test_import_csv_grades(self, client, lecturer, student, grade_batch, assignment, enrollment):
        client.force_authenticate(user=lecturer)
        csv_data = "student_id,student_name,email,score,feedback\nSTU2025001,Jane Doe,student_test@uniportal.edu,95,Great work on AVL rotations!\n"
        csv_file = SimpleUploadedFile("grades.csv", csv_data.encode("utf-8"), content_type="text/csv")

        res = client.post(
            f"/api/v1/grades/batches/{grade_batch.id}/import-csv/",
            data={"file": csv_file},
            format="multipart",
        )
        assert res.status_code == 200
        assert res.data["imported_count"] == 1
        assert len(res.data["errors"]) == 0

        grade = Grade.objects.get(assignment=assignment, student=student)
        assert grade.score == Decimal("95")
        assert grade.letter_grade == "A"
        assert grade.feedback == "Great work on AVL rotations!"
