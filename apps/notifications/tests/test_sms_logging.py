import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.notifications.models import SMSLog
from apps.notifications.sms import send_sms, check_sms_status, resend_sms

User = get_user_model()


@pytest.fixture
def superadmin_user(db):
    return User.objects.create_superuser(
        email="sms_superadmin@uniportal.edu",
        password="supersecretpassword123",
        first_name="Super",
        last_name="Auditor"
    )


@pytest.fixture
def student_user(db):
    return User.objects.create_user(
        email="sms_student@uniportal.edu",
        password="studentpassword123",
        role="student",
        first_name="Ama",
        last_name="Acheampong",
        phone="0241002003"
    )


@pytest.mark.django_db
class TestSMSLoggingAndDispatch:
    def test_send_sms_simulation_persists_log(self, student_user, monkeypatch):
        monkeypatch.setenv("SMS_SIMULATION_MODE", "1")
        monkeypatch.setenv("ARKESEL_API_KEY", "")
        res = send_sms(
            phone=student_user.phone,
            message="Your portal credentials: Username: test, Pass: 123",
            sender_id="ASDAM",
            recipient_name=student_user.full_name,
            user=student_user,
            purpose="fresher_credentials"
        )
        assert res["success"] is True
        assert res.get("sms_log_id") is not None

        log = SMSLog.objects.get(id=res["sms_log_id"])
        assert log.recipient_phone == "+233241002003"
        assert log.recipient_name == student_user.full_name
        assert log.purpose == "fresher_credentials"
        assert log.status == SMSLog.DeliveryStatus.SIMULATED
        assert log.provider == "Arkesel (Simulated)"
        assert log.provider_message_id.startswith("SIM-")
        assert log.sent_at is not None
        assert log.delivered_at is not None

    def test_send_sms_gateway_response_updates_log(self, student_user, monkeypatch):
        monkeypatch.setenv("ARKESEL_API_KEY", "dummy-api-key")
        class MockResp:
            status_code = 200
            def json(self):
                return {"status": "success", "data": [{"id": "ARK-TEST-789", "status": "DELIVERED"}]}
            @property
            def text(self):
                return '{"status": "success"}'
        import requests
        monkeypatch.setattr(requests, "post", lambda *a, **kw: MockResp())
        monkeypatch.setattr(requests, "get", lambda *a, **kw: MockResp())

        res = send_sms(
            phone=student_user.phone,
            message="Gateway test",
            recipient_name=student_user.full_name,
            user=student_user
        )
        assert res["success"] is True
        log = SMSLog.objects.get(id=res["sms_log_id"])
        assert log.provider_message_id == "ARK-TEST-789"
        assert log.status == SMSLog.DeliveryStatus.DELIVERED
        assert log.delivered_at is not None

    def test_send_sms_empty_phone_records_failed_log(self):
        res = send_sms(phone="", message="Testing invalid phone", purpose="alert")
        assert res["success"] is False
        assert res.get("sms_log_id") is not None

        log = SMSLog.objects.get(id=res["sms_log_id"])
        assert log.status == SMSLog.DeliveryStatus.FAILED
        assert "Invalid" in log.error_detail

    def test_resend_sms_increments_retries(self, student_user):
        res1 = send_sms(phone=student_user.phone, message="First attempt", user=student_user)
        log1 = SMSLog.objects.get(id=res1["sms_log_id"])
        assert log1.retries_count == 0

        res2 = resend_sms(log1.id)
        assert res2["success"] is True
        log1.refresh_from_db()
        assert log1.retries_count == 1


@pytest.mark.django_db
class TestSMSLogAPIAndSecurity:
    def test_student_forbidden_from_sms_logs(self, student_user):
        client = APIClient()
        client.force_authenticate(user=student_user)

        res = client.get("/api/v1/notifications/sms/")
        assert res.status_code == 403

        res_stats = client.get("/api/v1/notifications/sms/stats/")
        assert res_stats.status_code == 403

    def test_superadmin_can_list_and_filter_sms_logs(self, superadmin_user, student_user):
        # Create a few logs
        SMSLog.objects.create(
            recipient_phone="+233241112233",
            recipient_name="Kofi Annan",
            message_body="Welcome to ASDAM",
            status=SMSLog.DeliveryStatus.DELIVERED,
            purpose="fresher_credentials",
            provider="Arkesel",
            provider_message_id="ARK-1001",
            sent_at=timezone.now(),
            delivered_at=timezone.now(),
        )
        SMSLog.objects.create(
            recipient_phone="+233509988776",
            recipient_name="Abena Osei",
            message_body="Failed dispatch",
            status=SMSLog.DeliveryStatus.FAILED,
            purpose="password_reset",
            provider="Arkesel",
            provider_message_id="ARK-1002",
            error_detail="Network timeout"
        )

        client = APIClient()
        client.force_authenticate(user=superadmin_user)

        # List all
        res = client.get("/api/v1/notifications/sms/")
        assert res.status_code == 200
        assert res.data["count"] >= 2

        # Filter by status
        res_filter = client.get("/api/v1/notifications/sms/?status=delivered")
        assert res_filter.status_code == 200
        for item in res_filter.data["results"]:
            assert item["status"] == "DELIVERED"

        # Search by phone / name
        res_search = client.get("/api/v1/notifications/sms/?search=Kofi")
        assert res_search.status_code == 200
        assert res_search.data["count"] == 1
        assert res_search.data["results"][0]["recipient_name"] == "Kofi Annan"

    def test_sms_stats_endpoint(self, superadmin_user):
        SMSLog.objects.create(
            recipient_phone="+233240000001",
            message_body="Test 1",
            status=SMSLog.DeliveryStatus.DELIVERED,
        )
        SMSLog.objects.create(
            recipient_phone="+233240000002",
            message_body="Test 2",
            status=SMSLog.DeliveryStatus.FAILED,
        )

        client = APIClient()
        client.force_authenticate(user=superadmin_user)

        res = client.get("/api/v1/notifications/sms/stats/")
        assert res.status_code == 200
        assert res.data["total_sms"] >= 2
        assert res.data["delivered"] >= 1
        assert res.data["failed"] >= 1
        assert "delivered_rate_pct" in res.data

    def test_sms_export_csv_endpoint(self, superadmin_user):
        SMSLog.objects.create(
            recipient_phone="+233240000001",
            recipient_name="Export Target",
            message_body="Message for CSV",
            status=SMSLog.DeliveryStatus.DELIVERED,
            provider_message_id="ARK-EXP-999"
        )

        client = APIClient()
        client.force_authenticate(user=superadmin_user)

        res = client.get("/api/v1/notifications/sms/export-csv/")
        assert res.status_code == 200
        assert res["Content-Type"] == "text/csv; charset=utf-8"
        content = res.content.decode("utf-8-sig")
        assert "ASDAM INSTITUTIONAL TELECOM & SMS DISPATCH LEDGER" in content
        assert "Export Target" in content
        assert "ARK-EXP-999" in content

    def test_sms_webhook_dlr_updates_delivery_status(self):
        log = SMSLog.objects.create(
            recipient_phone="+233240001234",
            recipient_name="Webhook Student",
            message_body="Webhook Test Message",
            status=SMSLog.DeliveryStatus.SUBMITTED,
            provider_message_id="ARK-DLR-555"
        )

        client = APIClient()
        # Webhook is public (AllowAny) for carrier callback
        res = client.post("/api/v1/notifications/sms/webhook/", {
            "id": "ARK-DLR-555",
            "status": "DELIVERED"
        }, format="json")

        assert res.status_code == 200
        assert res.data["status"] == "updated"

        log.refresh_from_db()
        assert log.status == SMSLog.DeliveryStatus.DELIVERED
        assert log.delivered_at is not None
