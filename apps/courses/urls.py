from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    CourseViewSet, EnrollmentViewSet, CategoryViewSet, LessonViewSet,
    ExamClearanceStatusView, ExamClearancePDFView
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")
router.register("lessons",     LessonViewSet,     basename="lesson")
router.register("",            CourseViewSet,     basename="course")

urlpatterns = [
    path("exam-clearance/status/", ExamClearanceStatusView.as_view(), name="exam-clearance-status"),
    path("exam-clearance/pdf/", ExamClearancePDFView.as_view(), name="exam-clearance-pdf"),
] + router.urls

