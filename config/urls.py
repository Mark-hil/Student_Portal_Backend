"""Root URL configuration."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.http import JsonResponse
from rest_framework_simplejwt.views import TokenRefreshView


def health(request):
    from django.db import connection
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False
    return JsonResponse({"status": "ok" if db_ok else "degraded", "db": db_ok, "version": "1.0.0"})


urlpatterns = [
    path("admin/",   admin.site.urls),
    path("health/",  health),
    # JWT
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Apps
    path("api/v1/auth/",          include("apps.users.urls.auth")),
    path("api/v1/users/",         include("apps.users.urls.users")),
    path("api/v1/courses/",       include("apps.courses.urls")),
    path("api/v1/grades/",        include("apps.grades.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/files/",         include("apps.files.urls")),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
