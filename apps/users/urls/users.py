from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.users.views import (
    MeView, ChangePasswordView, UserViewSet, SystemStatsView,
    AvatarUploadView, CompleteRegistrationView
)

router = DefaultRouter()
router.register("manage", UserViewSet, basename="manage-users")

urlpatterns = [
    path("me/",                          MeView.as_view(),                   name="me"),
    path("me/complete-registration/",    CompleteRegistrationView.as_view(), name="complete-registration"),
    path("me/avatar/",                   AvatarUploadView.as_view(),         name="user-avatar"),
    path("me/change-password/",          ChangePasswordView.as_view(),       name="change-password"),
    path("stats/",                       SystemStatsView.as_view(),          name="stats"),
    path("export-students/",             UserViewSet.as_view({"get": "export_students"}), name="export-students"),
    path("", include(router.urls)),
]
