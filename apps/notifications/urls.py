from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet, SMSLogViewSet

router = DefaultRouter()
router.register("sms", SMSLogViewSet, basename="sms-log")
router.register("", NotificationViewSet, basename="notification")

urlpatterns = router.urls
