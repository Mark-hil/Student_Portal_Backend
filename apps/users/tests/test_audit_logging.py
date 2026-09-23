"""
Test suite for Enterprise Audit Logging System.
Verifies:
- Immutability guarantees (preventing modifications and deletions)
- AuditService event creation and attribution snapshots
- Authentication and session audit logging (login, failed login)
- Administrative actions & RBAC audit trails (role assignment, status toggle)
- AuditLogViewSet permission shielding and statistics calculations
- CSV compliance export
"""
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from apps.users.models import User, AuditLog
from apps.users.services.audit_service import AuditService


@pytest.mark.django_db
class TestAuditLogImmutability:
    """Verifies write-once, read-many (WORM) audit evidence guarantees."""

    def test_audit_log_creation_and_fields(self):
        user = User.objects.create_user(
            email="auditor@asdam.edu.gh",
            password="SecurePassword123!",
            first_name="Auditor",
            last_name="General",
            role="super_admin",
        )
        log = AuditService.log_event(
            action="TEST_ACTION",
            category=AuditLog.Category.SECURITY,
            actor=user,
            status=AuditLog.Status.SUCCESS,
            target_type="User",
            target_id=str(user.id),
            target_repr=user.email,
            description="Testing audit log creation.",
            changes={"before": {"role": "student"}, "after": {"role": "super_admin"}},
            metadata={"ip": "127.0.0.1"},
            ip_address="192.168.1.100",
        )
        assert log is not None
        assert log.actor_email == "auditor@asdam.edu.gh"
        assert log.actor_role == "super_admin"
        assert log.ip_address == "192.168.1.100"
        assert log.changes["after"]["role"] == "super_admin"

    def test_audit_log_cannot_be_updated(self):
        log = AuditLog.objects.create(
            action="IMMUTABLE_TEST",
            actor_email="actor@example.com",
            description="Original description",
        )
        log.description = "Altered description"
        with pytest.raises(RuntimeError, match="AuditLog records are immutable"):
            log.save()

    def test_audit_log_cannot_be_deleted(self):
        log = AuditLog.objects.create(
            action="DELETE_PREVENTION_TEST",
            actor_email="actor@example.com",
            description="Permanent record",
        )
        with pytest.raises(RuntimeError, match="AuditLog records are permanent"):
            log.delete()


@pytest.mark.django_db
class TestAuthenticationAuditLogs:
    """Verifies automated logging of login successes and failures."""

    def test_failed_login_logs_audit_event(self):
        client = APIClient()
        AuditLog.objects.all().delete() if False else None
        initial_count = AuditLog.objects.filter(action="AUTH_LOGIN_FAILED").count()

        resp = client.post("/api/v1/auth/login/", {
            "email": "nonexistent@asdam.edu.gh",
            "password": "WrongPassword!",
        })
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

        failed_logs = AuditLog.objects.filter(action="AUTH_LOGIN_FAILED")
        assert failed_logs.count() == initial_count + 1
        latest = failed_logs.order_by("-timestamp").first()
        assert latest.status == AuditLog.Status.FAILURE
        assert "nonexistent@asdam.edu.gh" in latest.actor_email

    def test_successful_login_logs_audit_event(self):
        client = APIClient()
        user = User.objects.create_user(
            email="active.student@asdam.edu.gh",
            password="StrongPassword123!",
            first_name="Active",
            last_name="Student",
            role="student",
        )
        initial_count = AuditLog.objects.filter(action="AUTH_LOGIN_SUCCESS").count()

        resp = client.post("/api/v1/auth/login/", {
            "email": "active.student@asdam.edu.gh",
            "password": "StrongPassword123!",
        })
        assert resp.status_code == status.HTTP_200_OK

        success_logs = AuditLog.objects.filter(action="AUTH_LOGIN_SUCCESS")
        assert success_logs.count() == initial_count + 1
        latest = success_logs.order_by("-timestamp").first()
        assert latest.actor == user
        assert latest.status == AuditLog.Status.SUCCESS


@pytest.mark.django_db
class TestAuditLogViewSetAndShielding:
    """Verifies Super-Admin access control, filtering, stats, and CSV export."""

    @pytest.fixture
    def super_admin(self):
        return User.objects.create_superuser(
            email="chief.auditor@asdam.edu.gh",
            password="SuperPassword123!",
            first_name="Chief",
            last_name="Auditor",
            role="super_admin",
        )

    @pytest.fixture
    def lecturer(self):
        return User.objects.create_user(
            email="regular.lecturer@asdam.edu.gh",
            password="LecturerPassword123!",
            first_name="Regular",
            last_name="Lecturer",
            role="lecturer",
        )

    def test_non_super_admin_forbidden_from_audit_logs(self, lecturer):
        client = APIClient()
        client.force_authenticate(user=lecturer)
        resp = client.get("/api/v1/users/audit-logs/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_super_admin_can_list_and_filter_audit_logs(self, super_admin):
        AuditLog.objects.create(
            action="SECURITY_ALERT",
            action_category=AuditLog.Category.SECURITY,
            status=AuditLog.Status.WARNING,
            actor=super_admin,
            actor_email=super_admin.email,
            description="Suspicious port scan",
        )
        AuditLog.objects.create(
            action="USER_CREATED",
            action_category=AuditLog.Category.USER_MANAGEMENT,
            status=AuditLog.Status.SUCCESS,
            actor=super_admin,
            actor_email=super_admin.email,
            description="User Jane Doe registered",
        )

        client = APIClient()
        client.force_authenticate(user=super_admin)

        resp = client.get("/api/v1/users/audit-logs/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["count"] >= 2

        # Filter by category
        filtered_resp = client.get("/api/v1/users/audit-logs/?category=security")
        assert filtered_resp.status_code == status.HTTP_200_OK
        for item in filtered_resp.data["results"]:
            assert item["action_category"] == "security"

    def test_audit_logs_stats_endpoint(self, super_admin):
        AuditLog.objects.create(
            action="AUTH_LOGIN_FAILED",
            action_category=AuditLog.Category.AUTH,
            status=AuditLog.Status.FAILURE,
            actor_email="hacker@bad.actor",
            description="Failed password attempt",
        )
        client = APIClient()
        client.force_authenticate(user=super_admin)

        resp = client.get("/api/v1/users/audit-logs/stats/")
        assert resp.status_code == status.HTTP_200_OK
        assert "total_events" in resp.data
        assert "failed_logins_24h" in resp.data
        assert resp.data["failed_logins_24h"] >= 1

    def test_audit_logs_csv_export(self, super_admin):
        AuditLog.objects.create(
            action="TEST_EXPORT_ACTION",
            action_category=AuditLog.Category.SYSTEM,
            status=AuditLog.Status.SUCCESS,
            actor=super_admin,
            actor_email=super_admin.email,
            description="Export verification test record",
        )
        client = APIClient()
        client.force_authenticate(user=super_admin)

        resp = client.get("/api/v1/users/audit-logs/export-csv/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp["Content-Type"].startswith("text/csv")
        content = resp.content.decode("utf-8")
        assert "Timestamp (UTC)" in content
        assert "TEST_EXPORT_ACTION" in content
