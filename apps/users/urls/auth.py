from django.urls import path
from apps.users.views import (
    RegisterView, LogoutView, CustomTokenObtainPairView,
    VerifyMOHView, RegisterMOHView
)

urlpatterns = [
    path("register/",     RegisterView.as_view(),              name="register"),
    path("verify-moh/",   VerifyMOHView.as_view(),             name="verify-moh"),
    path("register-moh/", RegisterMOHView.as_view(),           name="register-moh"),
    path("login/",        CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("logout/",       LogoutView.as_view(),                name="logout"),
]
