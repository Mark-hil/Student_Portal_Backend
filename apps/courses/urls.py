from rest_framework.routers import DefaultRouter
from .views import CourseViewSet, EnrollmentViewSet, CategoryViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")
router.register("", CourseViewSet, basename="course")

urlpatterns = router.urls
