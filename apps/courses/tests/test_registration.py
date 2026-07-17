import pytest
from datetime import time
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.courses.models import Course, Enrollment, CourseSchedule
from apps.courses.registration import RegistrationService, RegistrationError

User = get_user_model()

@pytest.fixture
def student(db):
    return User.objects.create_user(email="student@test.com", password="password", role="student")

@pytest.fixture
def course(db):
    return Course.objects.create(code="CS101", slug="cs101", title="Intro", credits=3, max_students=10, semester="FA24", status="active", start_date=timezone.now().date())

@pytest.mark.django_db
class TestRegistrationEngine:
    def test_successful_registration(self, student, course):
        svc = RegistrationService(student, "FA24")
        enr = svc.register(course)
        assert enr.status == "active"
        assert Enrollment.objects.count() == 1

    def test_credit_limit_exceeded(self, student):
        c1 = Course.objects.create(code="CS1", slug="cs1", credits=10, max_students=10, status="active", semester="FA24", start_date=timezone.now().date())
        c2 = Course.objects.create(code="CS2", slug="cs2", credits=9, max_students=10, status="active", semester="FA24", start_date=timezone.now().date())
        svc = RegistrationService(student, "FA24")
        svc.register(c1)
        with pytest.raises(RegistrationError) as exc:
            svc.register(c2)
        assert exc.value.code == "credit_limit_exceeded"

    def test_prerequisites_not_met(self, student, course):
        prereq = Course.objects.create(code="CS099", slug="cs099", credits=3, max_students=10, status="active", semester="FA23", start_date=timezone.now().date())
        course.prerequisites.add(prereq)
        
        svc = RegistrationService(student, "FA24")
        with pytest.raises(RegistrationError) as exc:
            svc.register(course)
        assert exc.value.code == "prerequisites_not_met"

    def test_schedule_conflict(self, student):
        c1 = Course.objects.create(code="CS1", slug="cs1", credits=3, max_students=10, status="active", semester="FA24", start_date=timezone.now().date())
        c2 = Course.objects.create(code="CS2", slug="cs2", credits=3, max_students=10, status="active", semester="FA24", start_date=timezone.now().date())
        
        CourseSchedule.objects.create(course=c1, day_of_week=0, start_time=time(9, 0), end_time=time(10, 30))
        CourseSchedule.objects.create(course=c2, day_of_week=0, start_time=time(9, 30), end_time=time(11, 0))
        
        svc = RegistrationService(student, "FA24")
        svc.register(c1)
        with pytest.raises(RegistrationError) as exc:
            svc.register(c2)
        assert exc.value.code == "schedule_conflict"

    def test_waitlist_logic(self, student, course):
        course.max_students = 1
        course.save()
        
        s1 = User.objects.create_user(email="s1@test.com", password="password", role="student")
        RegistrationService(s1, "FA24").register(course)
        
        # Max capacity is 1, so student 2 should be waitlisted
        svc = RegistrationService(student, "FA24")
        enr = svc.register(course)
        assert enr.status == "waitlisted"
        
        # Student 1 drops, Student 2 is promoted
        RegistrationService(s1, "FA24").drop(Enrollment.objects.get(student=s1))
        
        enr.refresh_from_db()
        assert enr.status == "active"
