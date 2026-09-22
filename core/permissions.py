"""
Custom DRF permission classes supporting Institutional Roles and Granular RBAC.

Roles:
- Super Admin (super_admin, admin)
- Academic Officer (academic_officer, staff)
- Head of Department (head_of_department, departmental-head)
- Finance Officer (finance, finance-officer)
- Lecturer (lecturer, instructor)
- Student (student)
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.users.constants import normalize_role, RoleChoice


class IsSuperAdmin(BasePermission):
    """Allows access only to Super Admins / System Admins."""
    message = "Permission denied: Requires Super Administrator privileges."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return bool(request.user.is_superuser or normalize_role(request.user.role) == RoleChoice.SUPER_ADMIN)


class IsAcademicOfficer(BasePermission):
    """Allows access to Academic Officers and Super Admins."""
    message = "Permission denied: Requires Academic Officer or Administrator privileges."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        norm = normalize_role(request.user.role)
        return norm in (RoleChoice.ACADEMIC_OFFICER, RoleChoice.SUPER_ADMIN)


class IsHeadOfDepartment(BasePermission):
    """Allows access to Department Heads and Super Admins."""
    message = "Permission denied: Requires Head of Department or Administrator privileges."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        norm = normalize_role(request.user.role)
        return norm in (RoleChoice.HEAD_OF_DEPARTMENT, RoleChoice.SUPER_ADMIN)


class IsFinanceOfficer(BasePermission):
    """Allows access to Finance Officers and Super Admins."""
    message = "Permission denied: Requires Finance Directorate privileges."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        norm = normalize_role(request.user.role)
        return norm in (RoleChoice.FINANCE, RoleChoice.SUPER_ADMIN)


class IsLecturer(BasePermission):
    """Allows access to Lecturers / Faculty and Super Admins."""
    message = "Permission denied: Requires Lecturer privileges."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        norm = normalize_role(request.user.role)
        return norm in (RoleChoice.LECTURER, RoleChoice.SUPER_ADMIN)


class IsStudent(BasePermission):
    """Allows access only to Student role."""
    message = "Permission denied: Restricted to enrolled students."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return normalize_role(request.user.role) == RoleChoice.STUDENT


# ── Granular Capability Permissions ──────────────────────────────────────────

def HasFunctionPermission(function_code: str):
    """
    Factory returning a DRF Permission class that checks whether the user
    has a specific functional capability (either through their role defaults or custom assignments).
    """
    class _FunctionPermission(BasePermission):
        message = f"Permission denied: Missing required capability '{function_code}'."

        def has_permission(self, request, view):
            if not (request.user and request.user.is_authenticated):
                return False
            if hasattr(request.user, "has_portal_permission"):
                return request.user.has_portal_permission(function_code)
            return False

    _FunctionPermission.__name__ = f"HasFunctionPermission_{function_code.replace('.', '_')}"
    return _FunctionPermission


def HasAnyFunctionPermission(*function_codes: str):
    """
    Factory returning a DRF Permission class that checks whether the user
    has AT LEAST ONE of the specified capabilities.
    """
    class _AnyFunctionPermission(BasePermission):
        message = f"Permission denied: Requires one of {list(function_codes)}."

        def has_permission(self, request, view):
            if not (request.user and request.user.is_authenticated):
                return False
            if hasattr(request.user, "has_portal_permission"):
                return any(request.user.has_portal_permission(code) for code in function_codes)
            return False

    return _AnyFunctionPermission


# ── Backward-Compatible Legacy Permission Classes ────────────────────────────

class IsInstructor(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        norm = normalize_role(request.user.role)
        return norm in (RoleChoice.LECTURER, RoleChoice.SUPER_ADMIN, RoleChoice.HEAD_OF_DEPARTMENT)


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        return normalize_role(request.user.role) == RoleChoice.SUPER_ADMIN


class IsAdminOrStaff(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True
        norm = normalize_role(request.user.role)
        if request.method in SAFE_METHODS:
            return (
                norm in (
                    RoleChoice.SUPER_ADMIN,
                    RoleChoice.ACADEMIC_OFFICER,
                    RoleChoice.HEAD_OF_DEPARTMENT,
                    RoleChoice.FINANCE,
                )
                or getattr(request.user, "has_portal_permission", lambda f: False)("students.view")
            )
        return norm in (RoleChoice.SUPER_ADMIN, RoleChoice.ACADEMIC_OFFICER, RoleChoice.HEAD_OF_DEPARTMENT)


class IsOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        owner = getattr(obj, "user", None) or getattr(obj, "student", None)
        return owner == request.user


class IsStudentRegistered(BasePermission):
    """
    Enforces that student users must have completed their mandatory profile registration
    before accessing sensitive portal features (e.g. course registration, grades, transcripts, fees).
    """
    message = "You must complete your mandatory student profile registration before accessing this portal feature."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if normalize_role(request.user.role) == RoleChoice.STUDENT:
            return bool(request.user.is_registered)
        return True
