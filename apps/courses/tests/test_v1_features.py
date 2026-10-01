import pytest
from decimal import Decimal
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from apps.users.models import User
from apps.courses.models import Course, Enrollment, Category
from apps.financials.models import FinancialHold, StudentAccountStatement
from apps.notifications.models import Announcement


@pytest.mark.django_db
class TestV1Features:
    @pytest.fixture
    def setup_data(self):
        admin = User.objects.create_user(
            email="principal@asdam.edu.gh",
            password="Password123!",
            first_name="Kwame",
            last_name="Mensah",
            role="super_admin",
            is_staff=True,
        )
        student = User.objects.create_user(
            email="student1@asdam.edu.gh",
            password="Password123!",
            first_name="Ama",
            last_name="Osei",
            student_id="STU-2024-001",
            moh_pin="NUR-987654",
            program="nursing",
            class_name="200",
            role="student",
        )
        category = Category.objects.create(name="Nursing Sciences", slug="nursing-sci")
        course = Course.objects.create(
            code="NUR 201",
            title="Pharmacology in Nursing",
            slug="nur-201",
            category=category,
            credits=3,
            status=Course.Status.ACTIVE,
        )
        Enrollment.objects.create(
            student=student,
            course=course,
            status=Enrollment.Status.ACTIVE,
        )
        statement = StudentAccountStatement.objects.create(
            student=student,
            semester="First Semester 2024/2025",
            total_billed=Decimal("4000.00"),
            total_paid=Decimal("4000.00"),
            balance=Decimal("0.00"),
            status=StudentAccountStatement.Status.PAID,
        )
        return {
            "admin": admin,
            "student": student,
            "course": course,
            "statement": statement,
        }

    def test_announcement_permissions_and_broadcast(self, setup_data):
        admin_client = APIClient()
        admin_client.force_authenticate(user=setup_data["admin"])

        student_client = APIClient()
        student_client.force_authenticate(user=setup_data["student"])

        # 1. Admin creates announcement
        res = admin_client.post(
            "/api/v1/notifications/announcements/",
            {
                "title": "Examination Regulations Memo",
                "content": "All students must be seated 30 minutes before exams.",
                "category": "examination",
                "target_audience": "students",
                "is_pinned": True,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        announcement_id = res.data["id"]
        assert res.data["is_pinned"] is True
        assert res.data["author_name"] == "Kwame Mensah"

        # 2. Student cannot create announcement (Forbidden)
        student_post = student_client.post(
            "/api/v1/notifications/announcements/",
            {"title": "Spam Notice", "content": "Hello"},
            format="json",
        )
        assert student_post.status_code == status.HTTP_403_FORBIDDEN

        # 3. Student can view published announcements
        student_get = student_client.get("/api/v1/notifications/announcements/")
        assert student_get.status_code == status.HTTP_200_OK
        # Check either paginated or direct list
        results = student_get.data.get("results", student_get.data) if isinstance(student_get.data, dict) else student_get.data
        assert any(str(item["id"]) == str(announcement_id) for item in results)

    def test_exam_clearance_eligibility_and_pdf(self, setup_data):
        student = setup_data["student"]
        client = APIClient()
        client.force_authenticate(user=student)

        # 1. Eligible student status
        status_res = client.get("/api/v1/courses/exam-clearance/status/")
        assert status_res.status_code == status.HTTP_200_OK
        assert status_res.data["is_eligible"] is True
        assert status_res.data["has_financial_hold"] is False
        assert status_res.data["registered_courses_count"] == 1
        assert status_res.data["total_credits"] == 3

        # 2. Download PDF
        pdf_res = client.get("/api/v1/courses/exam-clearance/pdf/")
        assert pdf_res.status_code == status.HTTP_200_OK
        assert pdf_res["Content-Type"] == "application/pdf"
        assert pdf_res.content.startswith(b"%PDF")

        # 3. Place an active financial hold -> clearance should be blocked
        hold = FinancialHold.objects.create(
            student=student,
            reason="Outstanding Library & Lab Fees",
            amount_due=Decimal("650.00"),
            is_active=True,
        )

        status_res2 = client.get("/api/v1/courses/exam-clearance/status/")
        assert status_res2.status_code == status.HTTP_200_OK
        assert status_res2.data["is_eligible"] is False
        assert status_res2.data["has_financial_hold"] is True
        assert status_res2.data["hold_reason"] == "Outstanding Library & Lab Fees"

        pdf_blocked = client.get("/api/v1/courses/exam-clearance/pdf/")
        assert pdf_blocked.status_code == status.HTTP_403_FORBIDDEN
        assert "Examination clearance blocked" in pdf_blocked.data["detail"]
