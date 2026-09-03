import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.users.models import UserProfile

User = get_user_model()

@pytest.fixture
def client():
    return APIClient()

@pytest.fixture
def student_user(db):
    user = User.objects.create_user(
        email="profile_student@uniportal.edu",
        password="password123",
        role="student",
        first_name="Alex",
        last_name="Mercer",
        student_id="STU-9999",
        department="Computer Science",
    )
    UserProfile.objects.create(user=user, major="Computer Science")
    return user

@pytest.mark.django_db
class TestUserProfile:
    def test_get_me(self, client, student_user):
        client.force_authenticate(user=student_user)
        res = client.get("/api/v1/users/me/")
        assert res.status_code == 200
        assert res.data["email"] == "profile_student@uniportal.edu"
        assert res.data["full_name"] == "Alex Mercer"
        assert res.data["profile"]["major"] == "Computer Science"

    def test_update_me(self, client, student_user):
        client.force_authenticate(user=student_user)
        payload = {
            "first_name": "Alexander",
            "phone": "+1234567890",
            "bio": "Updated academic bio",
            "profile": {
                "major": "Software Engineering"
            }
        }
        res = client.patch("/api/v1/users/me/", data=payload, format="json")
        assert res.status_code == 200
        assert res.data["first_name"] == "Alexander"
        assert res.data["full_name"] == "Alexander Mercer"
        assert res.data["phone"] == "+1234567890"
        assert res.data["bio"] == "Updated academic bio"
        assert res.data["profile"]["major"] == "Software Engineering"

    def test_change_password(self, client, student_user):
        client.force_authenticate(user=student_user)
        payload = {
            "current_password": "password123",
            "new_password": "newpassword1234",
        }
        res = client.post("/api/v1/users/me/change-password/", data=payload, format="json")
        assert res.status_code == 200
        assert res.data["detail"] == "Password updated successfully."

        # Verify old password no longer works
        student_user.refresh_from_db()
        assert not student_user.check_password("password123")
        assert student_user.check_password("newpassword1234")
