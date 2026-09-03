"""
Tests for Course Registration Deadlines, Window Reopening, and CSV Reports.
"""
from datetime import timedelta
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.courses.models import Course, RegistrationWindow, Enrollment, Category
from apps.courses.registration import RegistrationService, RegistrationError

User = get_user_model()


@pytest.mark.django_db
class TestRegistrationDeadlinesAndReports:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = APIClient()
        self.category = Category.objects.create(name="CS", slug="cs")
        self.course = Course.objects.create(
            code="CS301",
            title="Distributed Systems",
            slug="cs301",
            credits=4,
            max_students=30,
            status=Course.Status.ACTIVE,
            semester="Spring 2025",
            category=self.category,
        )
        self.student = User.objects.create_user(
            email="student_deadline@university.edu",
            password="password123",
            first_name="Alice",
            last_name="Deadline",
            student_id="STU9901",
            role=User.Role.STUDENT,
        )
        self.unregistered_student = User.objects.create_user(
            email="student_unreg@university.edu",
            password="password123",
            first_name="Bob",
            last_name="Unregistered",
            student_id="STU9902",
            role=User.Role.STUDENT,
        )
        self.admin = User.objects.create_superuser(
            email="admin_deadline@university.edu",
            password="password123",
            first_name="Admin",
            last_name="Officer",
            role=User.Role.ADMIN,
        )

    def test_registration_blocked_when_window_closed(self):
        """Student cannot register if deadline has passed."""
        now = timezone.now()
        RegistrationWindow.objects.create(
            semester="Spring 2025",
            opens_at=now - timedelta(days=10),
            closes_at=now - timedelta(days=1),  # Deadline passed yesterday
            is_active=True,
        )
        service = RegistrationService(self.student, "Spring 2025")
        with pytest.raises(RegistrationError) as exc:
            service.register(self.course)
        assert exc.value.code == "registration_closed"

    def test_registration_allowed_when_window_open(self):
        """Student can register when window is active and current."""
        now = timezone.now()
        RegistrationWindow.objects.create(
            semester="Spring 2025",
            opens_at=now - timedelta(days=2),
            closes_at=now + timedelta(days=5),
            is_active=True,
        )
        service = RegistrationService(self.student, "Spring 2025")
        enrollment = service.register(self.course)
        assert enrollment.status == Enrollment.Status.ACTIVE

    def test_window_extension_and_reopen(self):
        """Extending or reopening window allows registration to resume."""
        now = timezone.now()
        window = RegistrationWindow.objects.create(
            semester="Spring 2025",
            opens_at=now - timedelta(days=10),
            closes_at=now - timedelta(days=1),
            is_active=True,
        )
        assert window.status_label == "closed"
        assert not window.is_open

        # Extend window by 7 days
        window.extend(days=7)
        assert window.is_open
        assert window.status_label == "open"

        service = RegistrationService(self.student, "Spring 2025")
        enrollment = service.register(self.course)
        assert enrollment.status == Enrollment.Status.ACTIVE

    def test_admin_manage_window_api(self):
        """Admin can extend or reopen registration window via API."""
        self.client.force_authenticate(user=self.admin)
        res = self.client.post("/api/v1/courses/registration-window/manage/", {
            "semester": "Spring 2025",
            "extend_days": 5,
        })
        assert res.status_code == 200
        assert res.data["is_open"] is True
        assert res.data["status_label"] == "open"

    def test_registration_stats_and_csv_reports(self):
        """Admin can fetch registration metrics and export registered/unregistered CSVs."""
        # Enroll Alice
        Enrollment.objects.create(
            student=self.student,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )

        self.client.force_authenticate(user=self.admin)

        # 1. Stats endpoint
        stats_res = self.client.get("/api/v1/courses/reports/registration-stats/?semester=Spring 2025")
        assert stats_res.status_code == 200
        assert stats_res.data["registered_students"] >= 1
        assert stats_res.data["unregistered_students"] >= 1

        # 2. Registered CSV
        reg_csv_res = self.client.get("/api/v1/courses/reports/registered-csv/?semester=Spring 2025")
        assert reg_csv_res.status_code == 200
        assert "text/csv" in reg_csv_res["Content-Type"]
        content = reg_csv_res.content.decode("utf-8-sig")
        assert "Alice" in content
        assert "CS301" in content

        # 3. Unregistered CSV
        unreg_csv_res = self.client.get("/api/v1/courses/reports/unregistered-csv/?semester=Spring 2025")
        assert unreg_csv_res.status_code == 200
        assert "text/csv" in unreg_csv_res["Content-Type"]
        content_unreg = unreg_csv_res.content.decode("utf-8-sig")
        assert "Bob" in content_unreg
        assert "Not Registered (0 Credits)" in content_unreg
