import pytest
from rest_framework import status
from rest_framework.test import APIClient
from apps.users.models import User
from apps.users.constants import (
    RoleChoice,
    normalize_role,
    PORTAL_ROLES,
    PORTAL_FUNCTIONS,
    ALL_FUNCTION_CODES,
    get_default_functions_for_role,
    get_effective_functions,
)
from core.permissions import (
    IsSuperAdmin,
    IsAcademicOfficer,
    IsHeadOfDepartment,
    IsFinanceOfficer,
    IsLecturer,
    IsStudent,
    HasFunctionPermission,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def super_admin(db):
    user = User.objects.create_user(
        email="superadmin_test@uniportal.edu",
        first_name="Super",
        last_name="Admin",
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
        email="academic_test@uniportal.edu",
        first_name="Academic",
        last_name="Officer",
        role=RoleChoice.ACADEMIC_OFFICER,
        is_staff=True,
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.fixture
def hod_user(db):
    user = User.objects.create_user(
        email="hod_test@uniportal.edu",
        first_name="Dept",
        last_name="Head",
        role=RoleChoice.HEAD_OF_DEPARTMENT,
        department="Computer Science",
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.fixture
def finance_user(db):
    user = User.objects.create_user(
        email="finance_test@uniportal.edu",
        first_name="Finance",
        last_name="Officer",
        role=RoleChoice.FINANCE,
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.fixture
def lecturer_user(db):
    user = User.objects.create_user(
        email="lecturer_test@uniportal.edu",
        first_name="Lecturer",
        last_name="Test",
        role=RoleChoice.LECTURER,
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.fixture
def student_user(db):
    user = User.objects.create_user(
        email="student_test@uniportal.edu",
        first_name="Alex",
        last_name="Student",
        role=RoleChoice.STUDENT,
        student_id="STU-9901",
    )
    user.set_password("pass123")
    user.save()
    return user


@pytest.mark.django_db
class TestRoleNormalizationAndConstants:
    def test_normalize_roles(self):
        assert normalize_role("super_admin") == RoleChoice.SUPER_ADMIN
        assert normalize_role("super-admin") == RoleChoice.SUPER_ADMIN
        assert normalize_role("admin") == RoleChoice.SUPER_ADMIN

        assert normalize_role("academic_officer") == RoleChoice.ACADEMIC_OFFICER
        assert normalize_role("academic-officer") == RoleChoice.ACADEMIC_OFFICER
        assert normalize_role("staff") == RoleChoice.ACADEMIC_OFFICER

        assert normalize_role("head_of_department") == RoleChoice.HEAD_OF_DEPARTMENT
        assert normalize_role("head-of-department") == RoleChoice.HEAD_OF_DEPARTMENT
        assert normalize_role("departmental-head") == RoleChoice.HEAD_OF_DEPARTMENT
        assert normalize_role("hod") == RoleChoice.HEAD_OF_DEPARTMENT

        assert normalize_role("finance") == RoleChoice.FINANCE
        assert normalize_role("finance-officer") == RoleChoice.FINANCE

        assert normalize_role("lecturer") == RoleChoice.LECTURER
        assert normalize_role("instructor") == RoleChoice.LECTURER

        assert normalize_role("student") == RoleChoice.STUDENT

    def test_portal_roles_and_functions_catalogs(self):
        assert len(PORTAL_ROLES) == 6
        role_codes = {r["code"] for r in PORTAL_ROLES}
        assert RoleChoice.SUPER_ADMIN in role_codes
        assert RoleChoice.ACADEMIC_OFFICER in role_codes
        assert RoleChoice.HEAD_OF_DEPARTMENT in role_codes
        assert RoleChoice.FINANCE in role_codes
        assert RoleChoice.LECTURER in role_codes
        assert RoleChoice.STUDENT in role_codes

        assert len(PORTAL_FUNCTIONS) > 15
        for fn in PORTAL_FUNCTIONS:
            assert "code" in fn and "name" in fn and "category" in fn


@pytest.mark.django_db
class TestUserPermissionsAndModelProperties:
    def test_user_role_properties(self, super_admin, academic_officer, hod_user, finance_user, lecturer_user, student_user):
        assert super_admin.is_super_admin is True
        assert super_admin.is_academic_officer is True
        assert super_admin.is_hod is True
        assert super_admin.is_finance_role is True
        assert super_admin.is_lecturer_role is True
        assert super_admin.is_student_role is False

        assert academic_officer.is_academic_officer is True
        assert academic_officer.is_super_admin is False

        assert hod_user.is_hod is True
        assert hod_user.is_super_admin is False

        assert finance_user.is_finance_role is True
        assert finance_user.is_super_admin is False

        assert lecturer_user.is_lecturer_role is True
        assert lecturer_user.is_instructor_role is True
        assert lecturer_user.is_super_admin is False

        assert student_user.is_student_role is True
        assert student_user.is_super_admin is False

    def test_effective_functions_and_custom_assignment(self, lecturer_user):
        # Lecturer default permissions
        defaults = get_default_functions_for_role(RoleChoice.LECTURER)
        assert "grades.enter" in defaults
        assert "grades.submit_batch" in defaults
        assert "users.manage_roles" not in defaults

        # Initially, user has role default capabilities
        assert lecturer_user.has_portal_permission("grades.enter") is True
        assert lecturer_user.has_portal_permission("users.manage_roles") is False

        # Assign custom capability
        lecturer_user.assigned_functions = ["users.manage_roles"]
        lecturer_user.save()

        assert "users.manage_roles" in lecturer_user.effective_functions
        assert lecturer_user.has_portal_permission("users.manage_roles") is True


@pytest.mark.django_db
class TestRolesAndPermissionsAPI:
    def test_get_roles_and_functions_catalog(self, api_client, super_admin):
        api_client.force_authenticate(user=super_admin)
        url = "/api/v1/users/manage/roles-and-functions/"
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "roles" in data
        assert "functions" in data
        assert len(data["roles"]) == 6

    def test_assign_role_and_functions_by_super_admin(self, api_client, super_admin, student_user):
        api_client.force_authenticate(user=super_admin)
        url = f"/api/v1/users/manage/{student_user.id}/assign-role-and-functions/"
        payload = {
            "role": "head_of_department",
            "assigned_functions": ["users.manage_roles", "financials.reports"],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_200_OK

        student_user.refresh_from_db()
        assert student_user.role == "head_of_department"
        assert "users.manage_roles" in student_user.assigned_functions
        assert "financials.reports" in student_user.assigned_functions
        assert student_user.has_portal_permission("users.manage_roles") is True

    def test_assign_role_and_functions_forbidden_for_student(self, api_client, student_user, lecturer_user):
        api_client.force_authenticate(user=student_user)
        url = f"/api/v1/users/manage/{lecturer_user.id}/assign-role-and-functions/"
        payload = {
            "role": "super_admin",
            "assigned_functions": [],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDRFPermissionClasses:
    def test_drf_role_permissions(self, rf, super_admin, academic_officer, hod_user, finance_user, lecturer_user, student_user):
        req_admin = rf.get("/")
        req_admin.user = super_admin

        req_academic = rf.get("/")
        req_academic.user = academic_officer

        req_hod = rf.get("/")
        req_hod.user = hod_user

        req_finance = rf.get("/")
        req_finance.user = finance_user

        req_lecturer = rf.get("/")
        req_lecturer.user = lecturer_user

        req_student = rf.get("/")
        req_student.user = student_user

        # IsSuperAdmin
        assert IsSuperAdmin().has_permission(req_admin, None) is True
        assert IsSuperAdmin().has_permission(req_academic, None) is False

        # IsAcademicOfficer
        assert IsAcademicOfficer().has_permission(req_academic, None) is True
        assert IsAcademicOfficer().has_permission(req_admin, None) is True
        assert IsAcademicOfficer().has_permission(req_student, None) is False

        # IsHeadOfDepartment
        assert IsHeadOfDepartment().has_permission(req_hod, None) is True
        assert IsHeadOfDepartment().has_permission(req_admin, None) is True
        assert IsHeadOfDepartment().has_permission(req_student, None) is False

        # IsFinanceOfficer
        assert IsFinanceOfficer().has_permission(req_finance, None) is True
        assert IsFinanceOfficer().has_permission(req_admin, None) is True
        assert IsFinanceOfficer().has_permission(req_student, None) is False

        # IsLecturer
        assert IsLecturer().has_permission(req_lecturer, None) is True
        assert IsLecturer().has_permission(req_admin, None) is True
        assert IsLecturer().has_permission(req_student, None) is False

        # IsStudent
        assert IsStudent().has_permission(req_student, None) is True
        assert IsStudent().has_permission(req_admin, None) is False

    def test_function_permission_factory(self, rf, lecturer_user, super_admin):
        PermClass = HasFunctionPermission("grades.enter")
        req_lecturer = rf.get("/")
        req_lecturer.user = lecturer_user

        req_admin = rf.get("/")
        req_admin.user = super_admin

        # Lecturer has grades.enter by default
        assert PermClass().has_permission(req_lecturer, None) is True
        # Super admin has all permissions
        assert PermClass().has_permission(req_admin, None) is True

        # Lecturer does not have users.manage_roles by default
        ManagePerm = HasFunctionPermission("users.manage_roles")
        assert ManagePerm().has_permission(req_lecturer, None) is False

    def test_legacy_and_hyphenated_roles_create_update_and_filter(self, api_client, super_admin, student_user):
        api_client.force_authenticate(user=super_admin)

        # 1. Update user with 'super-admin'
        url = f"/api/v1/users/manage/{student_user.id}/"
        res = api_client.patch(url, {"role": "super-admin"}, format="json")
        assert res.status_code == 200, res.data
        assert res.data["role"] == "super_admin"
        student_user.refresh_from_db()
        assert student_user.role == "super_admin"

        # 2. Update user with 'departmental-head'
        res = api_client.patch(url, {"role": "departmental-head"}, format="json")
        assert res.status_code == 200, res.data
        assert res.data["role"] == "head_of_department"
        student_user.refresh_from_db()
        assert student_user.role == "head_of_department"

        # 3. Update user with 'academic-officer'
        res = api_client.patch(url, {"role": "academic-officer"}, format="json")
        assert res.status_code == 200, res.data
        assert res.data["role"] == "academic_officer"
        student_user.refresh_from_db()
        assert student_user.role == "academic_officer"

        # 4. Update user with 'finance-officer'
        res = api_client.patch(url, {"role": "finance-officer"}, format="json")
        assert res.status_code == 200, res.data
        assert res.data["role"] == "finance"
        student_user.refresh_from_db()
        assert student_user.role == "finance"

        # 5. Filter users with 'super-admin'
        filter_res = api_client.get("/api/v1/users/manage/?role=super-admin")
        assert filter_res.status_code == 200
        emails = [u["email"] for u in filter_res.data.get("results", filter_res.data)]
        assert super_admin.email in emails
