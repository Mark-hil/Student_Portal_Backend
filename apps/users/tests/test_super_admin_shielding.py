import pytest
from rest_framework import status
from rest_framework.test import APIClient
from apps.users.models import User
from apps.users.constants import RoleChoice


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def super_admin(db):
    user = User.objects.create_user(
        email="chief_admin@uniportal.edu",
        first_name="Chief",
        last_name="SuperAdmin",
        role=RoleChoice.SUPER_ADMIN,
        is_staff=True,
        is_superuser=True,
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.fixture
def second_super_admin(db):
    user = User.objects.create_user(
        email="second_admin@uniportal.edu",
        first_name="Second",
        last_name="SuperAdmin",
        role=RoleChoice.SUPER_ADMIN,
        is_staff=True,
        is_superuser=True,
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.fixture
def academic_officer(db):
    user = User.objects.create_user(
        email="academic_shield@uniportal.edu",
        first_name="Academic",
        last_name="Officer",
        role=RoleChoice.ACADEMIC_OFFICER,
        is_staff=True,
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.fixture
def student_user(db):
    user = User.objects.create_user(
        email="student_shield@uniportal.edu",
        first_name="John",
        last_name="Doe",
        role=RoleChoice.STUDENT,
        student_id="ASDAM/NUR/26/999",
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.mark.django_db
class TestSuperAdminShielding:
    def test_super_admin_hidden_from_non_superadmin_user_list(self, api_client, academic_officer, super_admin):
        api_client.force_authenticate(user=academic_officer)
        response = api_client.get("/api/v1/users/manage/?user_type=staff")
        assert response.status_code == status.HTTP_200_OK
        emails = [u["email"] for u in response.data.get("results", response.data)]
        assert super_admin.email not in emails
        assert academic_officer.email in emails

    def test_super_admin_visible_to_super_admin_user_list(self, api_client, super_admin, second_super_admin):
        api_client.force_authenticate(user=super_admin)
        response = api_client.get("/api/v1/users/manage/?user_type=staff")
        assert response.status_code == status.HTTP_200_OK
        emails = [u["email"] for u in response.data.get("results", response.data)]
        assert super_admin.email in emails
        assert second_super_admin.email in emails

    def test_academic_officer_cannot_view_or_modify_super_admin_role(self, api_client, academic_officer, super_admin):
        api_client.force_authenticate(user=academic_officer)
        url = f"/api/v1/users/manage/{super_admin.id}/assign-role-and-functions/"
        response = api_client.post(url, {"role": "lecturer", "assigned_functions": []}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_academic_officer_cannot_escalate_user_to_super_admin(self, api_client, academic_officer, student_user):
        api_client.force_authenticate(user=academic_officer)
        url = f"/api/v1/users/manage/{student_user.id}/assign-role-and-functions/"
        response = api_client.post(url, {"role": "super_admin", "assigned_functions": []}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_academic_officer_cannot_toggle_super_admin_status(self, api_client, academic_officer, super_admin):
        api_client.force_authenticate(user=academic_officer)
        url = f"/api/v1/users/manage/{super_admin.id}/toggle-status/"
        response = api_client.post(url)
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    def test_super_admin_cannot_suspend_themselves(self, api_client, super_admin):
        api_client.force_authenticate(user=super_admin)
        url = f"/api/v1/users/manage/{super_admin.id}/toggle-status/"
        response = api_client.post(url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_academic_officer_cannot_reset_super_admin_password(self, api_client, academic_officer, super_admin):
        api_client.force_authenticate(user=academic_officer)
        url = f"/api/v1/users/manage/{super_admin.id}/reset-password/"
        response = api_client.post(url, {"new_password": "NewSecretPass1!"})
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    def test_academic_officer_cannot_delete_super_admin(self, api_client, academic_officer, super_admin):
        api_client.force_authenticate(user=academic_officer)
        url = f"/api/v1/users/manage/{super_admin.id}/"
        response = api_client.delete(url)
        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    def test_roles_and_functions_catalog_omits_super_admin_for_subordinates(self, api_client, academic_officer):
        api_client.force_authenticate(user=academic_officer)
        url = "/api/v1/users/manage/roles-and-functions/"
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        role_codes = [r["code"] for r in response.data.get("roles", [])]
        assert "super_admin" not in role_codes
        assert "academic_officer" in role_codes

    def test_roles_and_functions_catalog_includes_super_admin_for_super_admin(self, api_client, super_admin):
        api_client.force_authenticate(user=super_admin)
        url = "/api/v1/users/manage/roles-and-functions/"
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        role_codes = [r["code"] for r in response.data.get("roles", [])]
        assert "super_admin" in role_codes
