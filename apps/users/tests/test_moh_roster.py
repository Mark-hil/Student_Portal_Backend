import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.users.services.id_generator import (
    generate_asdam_student_id,
    normalize_program,
    normalize_class_name,
)
from apps.users.services.roster_service import process_roster_csv

User = get_user_model()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email="admin_moh@uniportal.edu", password="adminpass123")


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email="staff_moh@uniportal.edu",
        password="staffpass123",
        role="staff",
        first_name="Staff",
        last_name="Officer"
    )


@pytest.fixture
def student_user(db):
    return User.objects.create_user(
        email="student_reg@uniportal.edu",
        password="studentpass123",
        role="student",
        first_name="Student",
        last_name="User"
    )


@pytest.mark.django_db
class TestASDAMStudentIdGenerator:
    def test_nursing_id_generation(self):
        sid1 = generate_asdam_student_id(program="Nursing", class_name="Level 100", year=2026)
        sid2 = generate_asdam_student_id(program="Nursing", class_name="100", year=2026)
        assert sid1 == "ASDAM/NUR/26/001"
        assert sid2 == "ASDAM/NUR/26/002"

    def test_midwifery_id_generation(self):
        sid_mid = generate_asdam_student_id(program="Midwifery", class_name="Level 100", year=2026)
        assert sid_mid == "ASDAM/MID/26/001"

    def test_program_normalization(self):
        assert normalize_program("Diploma in General Nursing") == "nursing"
        assert normalize_program("RGN") == "nursing"
        assert normalize_program("Registered Midwifery") == "midwifery"
        assert normalize_program("MID") == "midwifery"

    def test_class_normalization(self):
        assert normalize_class_name("Level 100") == "100"
        assert normalize_class_name("Class 2") == "CLASS-2"
        assert normalize_class_name("") == "100"


@pytest.mark.django_db
class TestMOHRosterUploadAndAuth:
    def test_roster_service_csv_import(self):
        csv_content = (
            "first_name,last_name,moh_pin,serial_number,program,class,year,phone,email\n"
            "Alice,Mensah,MOH-NUR-001,SN-1001,Nursing,Level 100,2026,0241000001,alice@example.com\n"
            "Beatrice,Kofi,MOH-MID-001,SN-1002,Midwifery,Level 100,2026,0241000002,\n"
        )
        result = process_roster_csv(csv_content)
        assert result["success"] is True
        assert result["imported_count"] == 2
        assert result["skipped_count"] == 0

        # Verify user 1: Nursing
        u1 = User.objects.get(moh_pin="MOH-NUR-001")
        assert u1.student_id == "ASDAM/NUR/26/001"
        assert u1.program == "nursing"
        assert u1.is_registered is False
        assert u1.check_password("SN-1001") is True  # hashed from serial number

        # Verify user 2: Midwifery
        u2 = User.objects.get(moh_pin="MOH-MID-001")
        assert u2.student_id == "ASDAM/MID/26/001"
        assert u2.program == "midwifery"
        assert u2.is_registered is False
        assert u2.email.endswith("@student.asdam.edu.gh")

    def test_admin_upload_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        csv_data = (
            "first_name,last_name,moh_pin,serial_number,program,class,year\n"
            "Cynthia,Boateng,MOH-NUR-099,SN-9901,Nursing,100,2026\n"
        )
        csv_file = SimpleUploadedFile("roster.csv", csv_data.encode("utf-8"), content_type="text/csv")

        res = client.post("/api/v1/users/manage/upload-moh-roster/", {"file": csv_file}, format="multipart")
        assert res.status_code == 200
        assert res.data["imported_count"] == 1
        assert res.data["students"][0]["student_id"].startswith("ASDAM/NUR/26/")

    def test_staff_officer_upload_permission(self, staff_user):
        client = APIClient()
        client.force_authenticate(user=staff_user)

        csv_data = (
            "first_name,last_name,moh_pin,serial_number,program,class,year\n"
            "Dorothy,Asare,MOH-MID-099,SN-9902,Midwifery,100,2026\n"
        )
        csv_file = SimpleUploadedFile("roster.csv", csv_data.encode("utf-8"), content_type="text/csv")

        res = client.post("/api/v1/users/manage/upload-moh-roster/", {"file": csv_file}, format="multipart")
        assert res.status_code == 200
        assert res.data["imported_count"] == 1

    def test_student_cannot_upload_roster(self, student_user):
        client = APIClient()
        client.force_authenticate(user=student_user)

        csv_file = SimpleUploadedFile("roster.csv", b"sample", content_type="text/csv")
        res = client.post("/api/v1/users/manage/upload-moh-roster/", {"file": csv_file}, format="multipart")
        assert res.status_code == 403

    def test_moh_verification_and_registration_flow(self):
        # Pre-seed uploaded student
        csv_content = (
            "first_name,last_name,moh_pin,serial_number,program,class,year\n"
            "Evelyn,Quaye,MOH-NUR-777,SN-7777,Nursing,Level 100,2026\n"
        )
        process_roster_csv(csv_content)

        client = APIClient()

        # Step 1: Verify MOH credentials
        verify_res = client.post("/api/v1/auth/verify-moh/", {
            "moh_pin": "MOH-NUR-777",
            "serial_number": "SN-7777"
        })
        assert verify_res.status_code == 200
        assert verify_res.data["status"] == "verified"
        assert verify_res.data["full_name"] == "Evelyn Quaye"
        assert verify_res.data["program"] == "nursing"
        assert verify_res.data["program_label"] == "Nursing"
        student_id = verify_res.data["student_id"]
        assert student_id.startswith("ASDAM/NUR/26/")

        # Test invalid PIN or Serial Number
        bad_verify = client.post("/api/v1/auth/verify-moh/", {
            "moh_pin": "MOH-NUR-777",
            "serial_number": "WRONG-SERIAL"
        })
        assert bad_verify.status_code == 400

        # Step 2: Register / Activate account with chosen password and personal email
        reg_res = client.post("/api/v1/auth/register-moh/", {
            "moh_pin": "MOH-NUR-777",
            "serial_number": "SN-7777",
            "password": "MySecretPassword2026!",
            "email": "evelyn.quaye@gmail.com",
            "phone": "0245558888"
        })
        assert reg_res.status_code == 200
        assert reg_res.data["status"] == "success"
        assert "tokens" in reg_res.data
        assert "access" in reg_res.data["tokens"]

        # Step 3: Test login using Student ID, MOH PIN, and Email
        # Login with Student ID
        login_sid = client.post("/api/v1/auth/login/", {
            "username": student_id,
            "password": "MySecretPassword2026!"
        })
        assert login_sid.status_code == 200
        assert "access" in login_sid.data

        # Login with MOH PIN
        login_pin = client.post("/api/v1/auth/login/", {
            "username": "MOH-NUR-777",
            "password": "MySecretPassword2026!"
        })
        assert login_pin.status_code == 200

        # Login with Personal Email
        login_email = client.post("/api/v1/auth/login/", {
            "email": "evelyn.quaye@gmail.com",
            "password": "MySecretPassword2026!"
        })
        assert login_email.status_code == 200

    def test_direct_initial_login_with_serial_number(self):
        # Pre-seed student who hasn't completed activation form yet
        csv_content = (
            "first_name,last_name,moh_pin,serial_number,program,class,year\n"
            "Felicia,Addo,MOH-MID-888,SN-VOUCHER888,Midwifery,Level 100,2026\n"
        )
        res = process_roster_csv(csv_content)
        student_id = res["students"][0]["student_id"]

        client = APIClient()

        # Login with MOH PIN + Serial Number as initial password
        initial_login = client.post("/api/v1/auth/login/", {
            "username": "MOH-MID-888",
            "password": "SN-VOUCHER888"
        })
        assert initial_login.status_code == 200
        assert initial_login.data["user"]["student_id"] == student_id
        assert initial_login.data["user"]["is_registered"] is False
