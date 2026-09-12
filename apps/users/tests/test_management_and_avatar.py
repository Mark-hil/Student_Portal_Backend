import io
import pytest
from PIL import Image
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()

@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email="admin_mgr@uniportal.edu", password="adminpassword123")

@pytest.fixture
def target_user(db):
    return User.objects.create_user(email="target@uniportal.edu", password="targetpassword123", role="student", first_name="Target", last_name="User")

@pytest.mark.django_db
class TestUserManagementAndAvatar:
    def test_admin_toggle_status(self, admin_user, target_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        assert target_user.is_active is True
        res = client.post(f"/api/v1/users/manage/{target_user.id}/toggle-status/")
        assert res.status_code == 200
        assert res.data["is_active"] is False

        # Toggle back
        res2 = client.post(f"/api/v1/users/manage/{target_user.id}/toggle-status/")
        assert res2.status_code == 200
        assert res2.data["is_active"] is True

    def test_admin_reset_password(self, admin_user, target_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        res = client.post(f"/api/v1/users/manage/{target_user.id}/reset-password/", {
            "new_password": "brandnewpassword123"
        })
        assert res.status_code == 200
        assert res.data["status"] == "success"

        # Check authentication with new password
        target_user.refresh_from_db()
        assert target_user.check_password("brandnewpassword123") is True

    def test_avatar_upload(self, target_user):
        client = APIClient()
        client.force_authenticate(user=target_user)

        # Create dummy image in memory
        image_io = io.BytesIO()
        image = Image.new("RGB", (100, 100), color="blue")
        image.save(image_io, format="JPEG")
        image_io.seek(0)
        uploaded_image = SimpleUploadedFile("avatar.jpg", image_io.getvalue(), content_type="image/jpeg")

        res = client.post("/api/v1/users/me/avatar/", {"avatar": uploaded_image}, format="multipart")
        assert res.status_code == 200
        assert "avatar" in res.data
        assert res.data["avatar"] is not None

    def test_admin_export_students(self, admin_user, target_user):
        from decimal import Decimal
        from apps.courses.models import Course
        from apps.grades.models import Transcript

        course = Course.objects.create(code="CS101", title="Intro to CS", credits=3)
        Transcript.objects.create(
            student=target_user,
            course=course,
            semester="2025-SPRING",
            semester_label="Spring 2025",
            score_percentage=Decimal("92.00"),
            final_grade="A",
            grade_points=Decimal("4.00"),
            credits_attempted=3,
            credits_earned=3,
            quality_points=Decimal("12.00")
        )

        client = APIClient()
        client.force_authenticate(user=admin_user)

        # Test query with role=&search= as sent from frontend
        res = client.get("/api/v1/users/manage/export-students/?role=&search=")
        assert res.status_code == 200
        assert res["Content-Type"] == "text/csv; charset=utf-8"
        content = res.content.decode("utf-8-sig")
        assert "INSTITUTIONAL STUDENT DIRECTORY" in content
        assert target_user.email in content
        assert "4.00" in content

