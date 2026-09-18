"""Custom DRF permission classes."""
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsInstructor(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ("instructor", "admin")


class IsStudent(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "student"


class IsOwnerOrReadOnly(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        owner = getattr(obj, "user", None) or getattr(obj, "student", None)
        return owner == request.user


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_authenticated and request.user.role == "admin"


class IsAdminOrStaff(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ("admin", "staff")


class IsStudentRegistered(BasePermission):
    """
    Enforces that student users must have completed their mandatory profile registration
    before accessing sensitive portal features (e.g. course registration, grades, transcripts, fees).
    """
    message = "You must complete your mandatory student profile registration before accessing this portal feature."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.role == "student":
            return bool(request.user.is_registered)
        return True

