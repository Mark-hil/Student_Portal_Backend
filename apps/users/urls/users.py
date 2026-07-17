from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.users.views import MeView, ChangePasswordView, UserViewSet, SystemStatsView

router = DefaultRouter()
router.register("manage", UserViewSet, basename="manage-users")

urlpatterns = [
    path("me/",                  MeView.as_view(),           name="me"),
    path("me/change-password/",  ChangePasswordView.as_view(), name="change-password"),
    path("stats/",               SystemStatsView.as_view(),  name="stats"),
    path("", include(router.urls)),
]
