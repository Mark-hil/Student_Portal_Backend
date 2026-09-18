import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.users.models import UserProfile
from apps.notifications.sms import normalize_phone_number, normalize_arkesel_phone, send_sms
from apps.notifications.tasks import dispatch_welcome_notifications, dispatch_registration_confirmation
from apps.users.services.roster_service import process_roster_csv

User = get_user_model()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email="admin_test@uniportal.edu", password="adminpass123")


@pytest.fixture
def student_unregistered(db):
    user = User.objects.create_user(
        email="freshman@student.asdam.edu.gh",
        password="MOH-SERIAL-999",
        student_id="ASDAM/NUR/26/099",
        moh_pin="MOH-NUR-2026-099",
        serial_number="MOH-SERIAL-999",
        first_name="Ama",
        last_name="Mensah",
        role="student",
        program="nursing",
        phone="0241234567",
        is_registered=False
    )
    UserProfile.objects.create(user=user, major="Nursing", academic_level="100")
    return user


@pytest.mark.django_db
class TestRegistrationOnboardingFlow:
    def test_phone_normalization(self):
        assert normalize_phone_number("0241234567") == "+233241234567"
        assert normalize_phone_number("+233241234567") == "+233241234567"
        assert normalize_phone_number("0509876543") == "+233509876543"
        assert normalize_arkesel_phone("0241234567") == "233241234567"
        assert normalize_arkesel_phone("+233241234567") == "233241234567"

    def test_send_sms_simulation(self):
        res = send_sms(phone="0241234567", message="Hello from ASDAM", sender_id="ASDAM")
        assert res["success"] is True
        assert res["phone"] == "+233241234567"
        assert "Arkesel" in res["provider"]


    def test_dispatch_welcome_notifications(self, student_unregistered, monkeypatch):
        from django.core import mail
        captured_sms = []

        def mock_send_sms(phone, message, sender_id="ASDAM"):
            captured_sms.append({"phone": phone, "message": message, "sender_id": sender_id})
            return {"success": True, "phone": phone, "provider": "Arkesel (Test Mock)"}

        monkeypatch.setattr("apps.notifications.sms.send_sms", mock_send_sms)

        res = dispatch_welcome_notifications(user_id=str(student_unregistered.id), raw_password="MOH-SERIAL-999")
        assert res["success"] is True
        assert res["email"]["success"] is True
        assert res["sms"]["success"] is True

        # Verify SMS text contains URL and exact credentials
        assert len(captured_sms) == 1
        sms = captured_sms[0]["message"]
        from django.conf import settings
        expected_url = settings.FRONTEND_URL.rstrip('/')
        assert f"Portal URL: {expected_url}" in sms
        assert "Student ID: ASDAM/NUR/26/099" in sms
        assert "Username: freshman@student.asdam.edu.gh" in sms
        assert "Temp Password: MOH-SERIAL-999" in sms

        # Verify Email outbox contains URL and exact credentials
        assert len(mail.outbox) >= 1
        sent_email = mail.outbox[-1]
        assert expected_url in sent_email.body
        assert "ASDAM/NUR/26/099" in sent_email.body
        assert "freshman@student.asdam.edu.gh" in sent_email.body
        assert "MOH-SERIAL-999" in sent_email.body

    def test_roster_import_dispatches_notifications(self, monkeypatch):
        def mock_send_sms(phone, message, sender_id="ASDAM"):
            return {"success": True, "phone": phone, "provider": "Mock"}
        monkeypatch.setattr("apps.notifications.sms.send_sms", mock_send_sms)

        csv_content = (
            "first_name,last_name,moh_pin,serial_number,program,phone,email\n"
            "Kofi,Antwi,MOH-NUR-2026-881,SN-881900,Nursing,0240001122,kofi.antwi@example.com\n"
        )
        res = process_roster_csv(csv_file=csv_content, default_year=2026, dry_run=False)
        assert res["success"] is True
        assert res["imported_count"] == 1
        assert res["notifications_count"] == 1
        created = User.objects.get(moh_pin="MOH-NUR-2026-881")
        assert created.student_id == "ASDAM/NUR/26/001"
        assert created.is_registered is False

    def test_complete_registration_api(self, student_unregistered):
        client = APIClient()
        client.force_authenticate(user=student_unregistered)

        payload = {
            "first_name": "Ama",
            "last_name": "Mensah",
            "ghana_card": "GHA-726189102-4",
            "gender": "Female",
            "date_of_birth": "2004-05-14",
            "birth_place": "Kumasi",
            "country_of_birth": "Ghana",
            "nationality": "Ghanaian",
            "languages_spoken": "English, Twi",
            "medical_condition": "None",
            "residential_address": "House 14, Ring Road Central",
            "city": "Kumasi",
            "region": "Ashanti",
            "district": "Kumasi Metropolitan",
            "digital_address": "AK-039-5028",
            "phone": "0241234567",
            "email": "ama.mensah@gmail.com",
            "guardian_name": "Kwame Mensah",
            "guardian_phone": "0209876543",
            "guardian_relationship": "Father",
            "new_password": "NewPermanentPass123!",
        }

        resp = client.post("/api/v1/users/me/complete-registration/", data=payload, format="json")
        assert resp.status_code == 200
        assert resp.data["status"] == "success"
        assert resp.data["user"]["is_registered"] is True

        student_unregistered.refresh_from_db()
        assert student_unregistered.is_registered is True
        assert student_unregistered.email == "ama.mensah@gmail.com"
        assert student_unregistered.check_password("NewPermanentPass123!") is True
        assert student_unregistered.profile.ghana_card == "GHA-726189102-4"
        assert student_unregistered.profile.digital_address == "AK-039-5028"
        assert student_unregistered.profile.guardian_name == "Kwame Mensah"
        assert student_unregistered.profile.registration_completed_at is not None

    def test_admin_resend_credentials(self, admin_user, student_unregistered):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        resp = client.post(f"/api/v1/users/manage/{student_unregistered.id}/resend-credentials/")
        assert resp.status_code == 200
        assert resp.data["status"] == "success"
