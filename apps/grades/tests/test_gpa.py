import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from apps.courses.models import Course, Enrollment
from apps.grades.models import Assignment, Grade, Transcript, SemesterRecord
from apps.grades.gpa import compute_course_final_grade, compute_semester_gpa, compute_cumulative_gpa

User = get_user_model()

@pytest.fixture
def student(db):
    return User.objects.create_user(email="student@test.com", password="password", role="student", first_name="Test", last_name="Student")

@pytest.fixture
def course(db):
    return Course.objects.create(code="CS101", slug="cs101", title="Intro", credits=3, max_students=10, semester="FA24", status="active")

@pytest.fixture
def enrollment(db, student, course):
    return Enrollment.objects.create(student=student, course=course, status="active")

@pytest.mark.django_db
class TestGPAEngine:
    def test_compute_course_final_grade_no_grades(self, student, course):
        res = compute_course_final_grade(student, course)
        assert res["letter"] is None
        assert res["grade_points"] is None

    def test_compute_course_final_grade(self, student, course, enrollment):
        a1 = Assignment.objects.create(course=course, title="Midterm", assignment_type="exam", max_score=100, weight=40)
        a2 = Assignment.objects.create(course=course, title="Final", assignment_type="exam", max_score=100, weight=60)
        
        Grade.objects.create(student=student, assignment=a1, score=80, is_published=True) # 32 points
        Grade.objects.create(student=student, assignment=a2, score=90, is_published=True) # 54 points => 86% => B
        
        res = compute_course_final_grade(student, course)
        assert res["letter"] == "B"
        assert res["grade_points"] == Decimal("3.0")
        assert res["percentage"] == 86.0

    def test_compute_semester_and_cumulative_gpa(self, student, course):
        Transcript.objects.create(student=student, course=course, semester="FA24", semester_label="Fall 2024",
                                  final_grade="A", grade_points=Decimal("4.0"), credits_attempted=3, credits_earned=3, quality_points=Decimal("12.0"))
        
        course2 = Course.objects.create(code="CS102", slug="cs102", title="Intro 2", credits=4, max_students=10, semester="FA24", status="active")
        Transcript.objects.create(student=student, course=course2, semester="FA24", semester_label="Fall 2024",
                                  final_grade="B", grade_points=Decimal("3.0"), credits_attempted=4, credits_earned=4, quality_points=Decimal("12.0"))
        
        # Total QP = 24.0, Total CR = 7 => GPA = 24 / 7 = 3.428... = 3.43
        sem_gpa = compute_semester_gpa(student, "FA24")
        cum_gpa = compute_cumulative_gpa(student)
        
        assert sem_gpa == Decimal("3.43")
        assert cum_gpa == Decimal("3.43")
