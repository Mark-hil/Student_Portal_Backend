import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.users.models import UserProfile, AcademicProgressionLog
from apps.courses.models import Course, Enrollment
from apps.grades.models import Transcript
from apps.financials.models import Payment

User = get_user_model()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        email="admin_prog@uniportal.edu",
        password="adminpassword123",
        role=User.Role.ADMIN,
    )


@pytest.fixture
def student_user(db):
    user = User.objects.create_user(
        email="student_prog@uniportal.edu",
        password="studentpassword123",
        role=User.Role.STUDENT,
        first_name="Kofi",
        last_name="Mensah",
        student_id="ASDAM/NUR/24/042",
        class_name="100",
        program="nursing",
        is_active=True,
    )
    UserProfile.objects.create(user=user, academic_level="100", major="Nursing")
    return user


@pytest.fixture
def course(db):
    return Course.objects.create(
        code="NUR101",
        title="Foundations of Nursing",
        slug="nur-101",
        description="Introduction to Nursing",
        semester="2024-SPRING",
    )


@pytest.mark.django_db
class TestStudentProgressionServiceAndApi:
    def test_promote_student_success(self, admin_user, student_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        res = client.post(f"/api/v1/users/manage/{student_user.id}/promote/", {
            "academic_year": "2024/2025",
            "notes": "Passed all Level 100 courses with GPA 3.50",
        })
        assert res.status_code == 200
        assert res.data["success"] is True
        assert res.data["from_level"] == "100"
        assert res.data["to_level"] == "200"

        student_user.refresh_from_db()
        assert student_user.class_name == "200"
        assert student_user.profile.academic_level == "200"
        assert student_user.academic_status == User.AcademicStatus.ACTIVE

        # Check log
        log = AcademicProgressionLog.objects.filter(student=student_user).first()
        assert log is not None
        assert log.action == AcademicProgressionLog.ActionType.PROMOTION
        assert log.from_level == "100"
        assert log.to_level == "200"
        assert log.performed_by == admin_user

    def test_promote_final_year_graduates_student(self, admin_user, student_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        student_user.class_name = "300"
        student_user.save()
        student_user.profile.academic_level = "300"
        student_user.profile.save()

        res = client.post(f"/api/v1/users/manage/{student_user.id}/promote/", {
            "academic_year": "2026/2027",
            "notes": "Completed 3-year Diploma in Nursing",
        })
        assert res.status_code == 200
        assert res.data["success"] is True
        assert res.data["academic_status"] == User.AcademicStatus.GRADUATED

        student_user.refresh_from_db()
        assert student_user.academic_status == User.AcademicStatus.GRADUATED
        assert student_user.graduation_date is not None

        log = AcademicProgressionLog.objects.filter(student=student_user, action="graduation").first()
        assert log is not None

    def test_demote_student_requires_reason(self, admin_user, student_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        student_user.class_name = "200"
        student_user.save()

        # Missing reason fails validation
        res = client.post(f"/api/v1/users/manage/{student_user.id}/demote/", {
            "reason": "",
        })
        assert res.status_code == 400

        # With valid reason
        res2 = client.post(f"/api/v1/users/manage/{student_user.id}/demote/", {
            "target_level": "100",
            "reason": "Failed clinical practicum prerequisites",
            "academic_year": "2024/2025",
        })
        assert res2.status_code == 200
        assert res2.data["success"] is True
        assert res2.data["to_level"] == "100"

        student_user.refresh_from_db()
        assert student_user.class_name == "100"
        assert student_user.academic_status == User.AcademicStatus.REPEATING

    def test_withdraw_student_drops_active_enrollments(self, admin_user, student_user, course):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        # Enroll student in active course
        enrollment = Enrollment.objects.create(
            student=student_user,
            course=course,
            status=Enrollment.Status.ACTIVE,
        )

        res = client.post(f"/api/v1/users/manage/{student_user.id}/withdraw/", {
            "reason": "Personal medical leave",
            "notes": "Approved by academic board",
        })
        assert res.status_code == 200
        assert res.data["success"] is True
        assert res.data["dropped_courses_count"] == 1

        student_user.refresh_from_db()
        assert student_user.academic_status == User.AcademicStatus.WITHDRAWN
        assert student_user.is_active is False
        assert student_user.withdrawal_date is not None

        # Check course enrollment status dropped with 'W' grade
        enrollment.refresh_from_db()
        assert enrollment.status == Enrollment.Status.DROPPED
        assert enrollment.final_grade == "W"

    def test_reinstate_withdrawn_student(self, admin_user, student_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        student_user.academic_status = User.AcademicStatus.WITHDRAWN
        student_user.is_active = False
        student_user.withdrawal_reason = "Voluntary leave"
        student_user.save()

        res = client.post(f"/api/v1/users/manage/{student_user.id}/reinstate/", {
            "target_level": "100",
            "notes": "Medical clearance obtained",
        })
        assert res.status_code == 200
        assert res.data["success"] is True

        student_user.refresh_from_db()
        assert student_user.academic_status == User.AcademicStatus.ACTIVE
        assert student_user.is_active is True
        assert student_user.withdrawal_date is None

    def test_soft_delete_and_restore(self, admin_user, student_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        # Soft delete via endpoint
        res = client.post(f"/api/v1/users/manage/{student_user.id}/soft-delete/", {
            "reason": "Archived student record",
        })
        assert res.status_code == 200

        # Normal User.objects excludes soft-deleted
        assert User.objects.filter(id=student_user.id).exists() is False
        # User.all_objects retains it
        assert User.all_objects.filter(id=student_user.id).exists() is True

        # Restore
        res_restore = client.post(f"/api/v1/users/manage/{student_user.id}/restore/")
        assert res_restore.status_code == 200

        student_user.refresh_from_db()
        assert student_user.is_active is True
        assert student_user.deleted_at is None
        assert User.objects.filter(id=student_user.id).exists() is True

    def test_hard_delete_precheck_and_guard(self, admin_user, student_user, course):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        # Before any official records, deletion precheck should report true
        precheck = client.get(f"/api/v1/users/manage/{student_user.id}/deletion-precheck/")
        assert precheck.status_code == 200
        assert precheck.data["can_hard_delete"] is True

        # Now add official transcript record
        Transcript.objects.create(
            student=student_user,
            course=course,
            semester="2024-SPRING",
            semester_label="Spring 2024",
            final_grade="A",
            grade_points=4.0,
            credits_earned=3,
        )

        # Precheck now reports cannot hard delete
        precheck2 = client.get(f"/api/v1/users/manage/{student_user.id}/deletion-precheck/")
        assert precheck2.status_code == 200
        assert precheck2.data["can_hard_delete"] is False
        assert len(precheck2.data["blockers"]) > 0

        # Attempting permanent delete without force fails
        res_fail = client.post(f"/api/v1/users/manage/{student_user.id}/permanent-delete/", {
            "force": False,
        })
        assert res_fail.status_code == 400
        assert "Cannot permanently delete" in res_fail.data["detail"]

    def test_bulk_promote_students(self, admin_user, student_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        student2 = User.objects.create_user(
            email="student2_prog@uniportal.edu",
            password="pass",
            role=User.Role.STUDENT,
            first_name="Akua",
            last_name="Boateng",
            student_id="ASDAM/MID/24/011",
            class_name="100",
            program="midwifery",
        )
        UserProfile.objects.create(user=student2, academic_level="100")

        res = client.post("/api/v1/users/manage/bulk-promote/", {
            "student_ids": [str(student_user.id), str(student2.id)],
            "target_level": "200",
            "academic_year": "2024/2025",
            "notes": "Bulk cohort progression",
        })
        assert res.status_code == 200
        assert len(res.data["succeeded"]) == 2
        assert len(res.data["failed"]) == 0

        student_user.refresh_from_db()
        student2.refresh_from_db()
        assert student_user.class_name == "200"
        assert student2.class_name == "200"

    def test_progression_history_endpoint(self, admin_user, student_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        # Promote
        client.post(f"/api/v1/users/manage/{student_user.id}/promote/", {"notes": "Promotion 1"})
        # Demote
        client.post(f"/api/v1/users/manage/{student_user.id}/demote/", {"reason": "Demotion reason"})

        res = client.get(f"/api/v1/users/manage/{student_user.id}/progression-history/")
        assert res.status_code == 200
        assert len(res.data) == 2
        actions = [log["action"] for log in res.data]
        assert "promotion" in actions
        assert "demotion" in actions
