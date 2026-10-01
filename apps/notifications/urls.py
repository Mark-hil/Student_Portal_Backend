from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet, SMSLogViewSet, AnnouncementViewSet

router = DefaultRouter()
router.register("announcements", AnnouncementViewSet, basename="announcement")
router.register("sms", SMSLogViewSet, basename="sms-log")
router.register("", NotificationViewSet, basename="notification")

urlpatterns = router.urls

