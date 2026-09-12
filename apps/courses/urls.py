from rest_framework.routers import DefaultRouter
from .views import CourseViewSet, EnrollmentViewSet, CategoryViewSet, LessonViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")
router.register("lessons",     LessonViewSet,     basename="lesson")
router.register("",            CourseViewSet,     basename="course")

urlpatterns = router.urls
