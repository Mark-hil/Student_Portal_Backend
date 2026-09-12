import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.courses.models import Course, Enrollment
from apps.grades.models import Assignment, Submission, Grade

User = get_user_model()

@pytest.fixture
def instructor(db):
    return User.objects.create_user(email="prof_grade@test.com", password="password", role="instructor", first_name="Grace", last_name="Hopper")

@pytest.fixture
def student(db):
    return User.objects.create_user(email="student_grade@test.com", password="password", role="student", first_name="Margaret", last_name="Hamilton")

@pytest.fixture
def course(db, instructor):
    c = Course.objects.create(
        code="CS301", slug="cs301", title="Compiler Design", credits=4,
        max_students=30, semester="FA24", status="active", start_date=timezone.now().date()
    )
    c.instructors.add(instructor)
    return c

@pytest.fixture
def assignment(db, course, instructor):
    return Assignment.objects.create(
        course=course,
        title="Lexer Implementation",
        assignment_type="assignment",
        max_score=100,
        weight=20,
        is_published=True,
        created_by=instructor,
    )

@pytest.mark.django_db
class TestSubmissionAndGrading:
    def test_student_submit_and_instructor_grade(self, instructor, student, course, assignment):
        Enrollment.objects.create(student=student, course=course, status="active", enrolled_at=timezone.now())

        # Student submits text solution
        stu_client = APIClient()
        stu_client.force_authenticate(user=student)
        submit_res = stu_client.post(f"/api/v1/grades/assignments/{assignment.id}/submit/", {
            "text_content": "https://github.com/student/lexer-repo with all test passes",
        })
        assert submit_res.status_code == 200
        submission_id = submit_res.data["id"]
        assert submit_res.data["status"] == "submitted"

        # Check student can view own submission
        my_sub = stu_client.get(f"/api/v1/grades/assignments/{assignment.id}/my-submission/")
        assert my_sub.status_code == 200
        assert my_sub.data["id"] == submission_id

        # Lecturer views submissions list
        inst_client = APIClient()
        inst_client.force_authenticate(user=instructor)
        subs_res = inst_client.get(f"/api/v1/grades/assignments/{assignment.id}/submissions/")
        assert subs_res.status_code == 200
        assert len(subs_res.data) == 1

        # Lecturer grades the submission
        grade_res = inst_client.post(f"/api/v1/grades/assignments/{assignment.id}/grade-submission/", {
            "submission_id": submission_id,
            "score": 95.5,
            "feedback": "Outstanding lexer implementation, very clean token handling!",
        })
        assert grade_res.status_code == 200
        assert grade_res.data["status"] == "graded"
        assert float(grade_res.data["score"]) == 95.5
        assert grade_res.data["feedback"] == "Outstanding lexer implementation, very clean token handling!"

        # Verify Grade model was updated
        grade = Grade.objects.filter(assignment=assignment, student=student).first()
        assert grade is not None
        assert float(grade.score) == 95.5
