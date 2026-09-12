import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.courses.models import Course, Enrollment, Lesson, LessonProgress

User = get_user_model()

@pytest.fixture
def instructor(db):
    return User.objects.create_user(email="prof@test.com", password="password", role="instructor", first_name="Alan", last_name="Turing")

@pytest.fixture
def student(db):
    return User.objects.create_user(email="student@test.com", password="password", role="student", first_name="Ada", last_name="Lovelace")

@pytest.fixture
def course(db, instructor):
    c = Course.objects.create(
        code="CS201", slug="cs201", title="Data Structures", credits=4,
        max_students=30, semester="FA24", status="active", start_date=timezone.now().date()
    )
    c.instructors.add(instructor)
    return c

@pytest.mark.django_db
class TestRosterAndLessons:
    def test_instructor_can_view_roster(self, instructor, student, course):
        Enrollment.objects.create(student=student, course=course, status="active", enrolled_at=timezone.now())
        client = APIClient()
        client.force_authenticate(user=instructor)

        res = client.get(f"/api/v1/courses/{course.id}/roster/")
        assert res.status_code == 200
        assert res.data["course_code"] == "CS201"
        assert res.data["total_enrolled"] == 1
        assert res.data["students"][0]["email"] == "student@test.com"

    def test_student_cannot_view_roster(self, student, course):
        client = APIClient()
        client.force_authenticate(user=student)

        res = client.get(f"/api/v1/courses/{course.id}/roster/")
        assert res.status_code == 403

    def test_lesson_creation_and_progress_toggle(self, instructor, student, course):
        Enrollment.objects.create(student=student, course=course, status="active", enrolled_at=timezone.now())

        # Instructor creates a lesson
        inst_client = APIClient()
        inst_client.force_authenticate(user=instructor)
        create_res = inst_client.post("/api/v1/courses/lessons/", {
            "course": str(course.id),
            "title": "Arrays and Linked Lists",
            "order": 1,
            "lesson_type": "reading",
            "content": "Deep dive into memory layout.",
            "duration_minutes": 45,
        })
        assert create_res.status_code == 201
        lesson_id = create_res.data["id"]

        # Student toggles lesson progress
        stu_client = APIClient()
        stu_client.force_authenticate(user=student)
        toggle_res = stu_client.post(f"/api/v1/courses/lessons/{lesson_id}/toggle-progress/")
        assert toggle_res.status_code == 200
        assert toggle_res.data["completed"] is True
        assert toggle_res.data["progress_pct"] == 100.0

        # Toggle again to uncomplete
        toggle_res2 = stu_client.post(f"/api/v1/courses/lessons/{lesson_id}/toggle-progress/")
        assert toggle_res2.status_code == 200
        assert toggle_res2.data["completed"] is False
        assert toggle_res2.data["progress_pct"] == 0.0
