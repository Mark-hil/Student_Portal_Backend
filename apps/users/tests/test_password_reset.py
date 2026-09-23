import pytest
from datetime import timedelta
from django.utils import timezone
from django.core import mail
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.users.models import PasswordResetToken, AuditLog
from apps.users.views import _hash_otp

User = get_user_model()


@pytest.fixture
def active_student(db):
    user = User.objects.create_user(
        email="reset.student@student.asdam.edu.gh",
        password="OldPassword123!",
        role="student",
        first_name="Kwesi",
        last_name="Arthur",
    )
    user.student_id = "ASDAM/NUR/26/555"
    user.phone = "0241999888"
    user.save()
    return user


@pytest.mark.django_db
class TestPasswordResetWorkflow:
    def test_password_reset_request_via_email(self, active_student):
        client = APIClient()
        resp = client.post("/api/v1/auth/password-reset/request/", {
            "identifier": active_student.email,
            "channel": "email"
        })
        assert resp.status_code == 200
        assert resp.data["status"] == "success"
        assert resp.data["channel"] == "email"
        assert "masked_destination" in resp.data

        # Verify token created in DB
        token = PasswordResetToken.objects.filter(user=active_student, is_used=False).first()
        assert token is not None
        assert token.channel == "email"
        assert token.destination == active_student.email
        assert token.expires_at > timezone.now()

        # Verify email sent
        assert len(mail.outbox) >= 1
        sent_email = mail.outbox[-1]
        assert active_student.email in sent_email.to
        assert "Password Reset Verification Code" in sent_email.subject

    def test_password_reset_request_via_sms_using_student_id(self, active_student, monkeypatch):
        captured_sms = []
        def mock_send_sms(phone, message, sender_id="ASDAM", *args, **kwargs):
            captured_sms.append({"phone": phone, "message": message, "sender_id": sender_id})
            return {"success": True, "phone": phone, "provider": "Mock"}
        monkeypatch.setattr("apps.users.views.send_sms", mock_send_sms)

        client = APIClient()
        resp = client.post("/api/v1/auth/password-reset/request/", {
            "identifier": "asdam/nur/26/555",  # case-insensitive check
            "channel": "sms"
        })
        assert resp.status_code == 200
        assert resp.data["status"] == "success"
        assert resp.data["channel"] == "sms"
        assert len(captured_sms) == 1
        assert captured_sms[0]["phone"] == active_student.phone
        assert "password reset code" in captured_sms[0]["message"]

    def test_password_reset_request_invalid_identifier_returns_404(self):
        client = APIClient()
        resp = client.post("/api/v1/auth/password-reset/request/", {
            "identifier": "nonexistent@user.com",
            "channel": "email"
        })
        assert resp.status_code == 404
        assert resp.data["error"] == "not_found"

    def test_password_reset_rate_limiting(self, active_student):
        client = APIClient()
        # Create 5 recent tokens
        for _ in range(5):
            PasswordResetToken.objects.create(
                user=active_student,
                token_hash="dummy_hash",
                channel="email",
                destination=active_student.email,
                expires_at=timezone.now() + timedelta(minutes=15),
            )

        resp = client.post("/api/v1/auth/password-reset/request/", {
            "identifier": active_student.email,
            "channel": "email"
        })
        assert resp.status_code == 429
        assert resp.data["error"] == "rate_limited"

    def test_password_reset_verify_code(self, active_student):
        client = APIClient()
        raw_code = "729401"
        PasswordResetToken.objects.create(
            user=active_student,
            token_hash=_hash_otp(raw_code),
            channel="email",
            destination=active_student.email,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        # 1. Invalid code
        bad_resp = client.post("/api/v1/auth/password-reset/verify/", {
            "identifier": active_student.email,
            "code": "000000"
        })
        assert bad_resp.status_code == 400
        assert bad_resp.data["error"] == "invalid_code"

        # 2. Valid code
        good_resp = client.post("/api/v1/auth/password-reset/verify/", {
            "identifier": active_student.email,
            "code": raw_code
        })
        assert good_resp.status_code == 200
        assert good_resp.data["status"] == "valid"

    def test_password_reset_confirm_fails_when_passwords_do_not_match(self, active_student):
        client = APIClient()
        raw_code = "314159"
        PasswordResetToken.objects.create(
            user=active_student,
            token_hash=_hash_otp(raw_code),
            channel="email",
            destination=active_student.email,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        resp = client.post("/api/v1/auth/password-reset/confirm/", {
            "identifier": active_student.email,
            "code": raw_code,
            "new_password": "NewSecretPassword123!",
            "confirm_password": "DifferentPassword123!",
        })
        assert resp.status_code == 400
        errors = resp.data.get("errors", resp.data)
        assert "confirm_password" in errors

    def test_password_reset_confirm_success_and_login(self, active_student, monkeypatch):
        captured_sms = []
        def mock_send_sms(phone, message, sender_id="ASDAM", *args, **kwargs):
            captured_sms.append({"phone": phone, "message": message, "sender_id": sender_id})
            return {"success": True, "phone": phone, "provider": "Mock"}
        monkeypatch.setattr("apps.users.views.send_sms", mock_send_sms)

        client = APIClient()
        raw_code = "889900"
        token = PasswordResetToken.objects.create(
            user=active_student,
            token_hash=_hash_otp(raw_code),
            channel="sms",
            destination=active_student.phone,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        resp = client.post("/api/v1/auth/password-reset/confirm/", {
            "identifier": active_student.student_id,
            "code": raw_code,
            "new_password": "BrandNewSecurePassword2026!",
            "confirm_password": "BrandNewSecurePassword2026!",
        })
        assert resp.status_code == 200
        assert resp.data["status"] == "success"
        assert "tokens" in resp.data
        assert "access" in resp.data["tokens"]

        # Verify token is marked used
        token.refresh_from_db()
        assert token.is_used is True

        # Verify audit log recorded
        audit = AuditLog.objects.filter(actor=active_student, action="USER_PASSWORD_RESET").first()
        assert audit is not None
        assert audit.status == AuditLog.Status.SUCCESS

        # Verify old password no longer works
        old_login = client.post("/api/v1/auth/login/", {
            "username": active_student.email,
            "password": "OldPassword123!"
        })
        assert old_login.status_code in (400, 401)

        # Verify new password works
        new_login = client.post("/api/v1/auth/login/", {
            "username": active_student.email,
            "password": "BrandNewSecurePassword2026!"
        })
        assert new_login.status_code == 200
        assert "access" in new_login.data
