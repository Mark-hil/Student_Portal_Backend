from django.urls import path
from apps.users.views import (
    RegisterView, LogoutView, CustomTokenObtainPairView,
    VerifyMOHView, RegisterMOHView,
    PasswordResetRequestView, PasswordResetVerifyView, PasswordResetConfirmView,
)

urlpatterns = [
    path("register/",               RegisterView.as_view(),               name="register"),
    path("verify-moh/",             VerifyMOHView.as_view(),              name="verify-moh"),
    path("register-moh/",           RegisterMOHView.as_view(),            name="register-moh"),
    path("login/",                  CustomTokenObtainPairView.as_view(),  name="token_obtain_pair"),
    path("logout/",                 LogoutView.as_view(),                 name="logout"),
    path("password-reset/request/", PasswordResetRequestView.as_view(),   name="password-reset-request"),
    path("password-reset/verify/",  PasswordResetVerifyView.as_view(),    name="password-reset-verify"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(),   name="password-reset-confirm"),
]

