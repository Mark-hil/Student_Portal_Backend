"""Production settings."""
import os
import dj_database_url
import sentry_sdk
from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
for default_host in ("localhost", "127.0.0.1", "0.0.0.0", "api", "nginx", "testserver"):
    if default_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(default_host)

# ── Neon / PostgreSQL Database ────────────────────────────────────────────────
# Supports direct Neon connection string via DATABASE_URL or individual DB_* variables.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", 600)),
            conn_health_checks=True,
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME":     os.environ.get("DB_NAME", "neondb"),
            "USER":     os.environ.get("DB_USER", "neondb_owner"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST":     os.environ.get("DB_HOST", "localhost"),
            "PORT":     os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", 600)),
            "OPTIONS": {"sslmode": "require"},
        }
    }

# Read Replica Configuration (optional for Neon; mirrors default if no distinct replica is set)
DATABASE_REPLICA_URL = os.environ.get("DATABASE_REPLICA_URL")
DB_REPLICA_HOST = os.environ.get("DB_REPLICA_HOST")

if DATABASE_REPLICA_URL:
    DATABASES["replica"] = dj_database_url.parse(
        DATABASE_REPLICA_URL,
        conn_max_age=int(os.environ.get("DB_CONN_MAX_AGE", 600)),
        conn_health_checks=True,
        ssl_require=True,
    )
    DATABASES["replica"]["TEST"] = {"MIRROR": "default"}
elif not DATABASE_URL and DB_REPLICA_HOST:
    DATABASES["replica"] = DATABASES["default"].copy()
    DATABASES["replica"]["HOST"] = DB_REPLICA_HOST
    DATABASES["replica"]["TEST"] = {"MIRROR": "default"}
else:
    # Default: mirror default Neon database for replica reads
    DATABASES["replica"] = DATABASES["default"].copy()
    DATABASES["replica"]["TEST"] = {"MIRROR": "default"}

DATABASE_ROUTERS = ["core.db_router.PrimaryReplicaRouter"]

# ── Security ──────────────────────────────────────────────────────────────────
SECURE_SSL_REDIRECT             = os.environ.get("SECURE_SSL_REDIRECT", "False").lower() in ("true", "1", "yes")
SECURE_HSTS_SECONDS             = 31536000 if SECURE_SSL_REDIRECT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS  = SECURE_SSL_REDIRECT
SECURE_HSTS_PRELOAD             = SECURE_SSL_REDIRECT
SECURE_CONTENT_TYPE_NOSNIFF     = True
SESSION_COOKIE_SECURE           = os.environ.get("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
CSRF_COOKIE_SECURE              = os.environ.get("CSRF_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
X_FRAME_OPTIONS                 = "DENY"
SECURE_PROXY_SSL_HEADER         = ("HTTP_X_FORWARDED_PROTO", "https")

# ── CORS ──────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()]
CORS_ALLOW_CREDENTIALS = True

# ── Cloudinary Media Storage ───────────────────────────────────────────────────
# In production, user uploads (avatars, assignments, documents) are stored on Cloudinary
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.environ.get("CLOUDINARY_CLOUD_NAME", ""),
    "API_KEY": os.environ.get("CLOUDINARY_API_KEY", ""),
    "API_SECRET": os.environ.get("CLOUDINARY_API_SECRET", ""),
}
CLOUDINARY_PROFILE_FOLDER = os.environ.get("CLOUDINARY_PROFILE_FOLDER", "uniportal-profile picture")

STORAGES = {
    "default": {
        "BACKEND": "core.storage.DynamicCloudinaryStorage",
    },
    "staticfiles": {
        "BACKEND": os.environ.get(
            "STATICFILES_STORAGE_BACKEND",
            "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        ),
    },
}

# ── Sentry ────────────────────────────────────────────────────────────────────
SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN and "project-id" not in SENTRY_DSN and "example" not in SENTRY_DSN and SENTRY_DSN.startswith("http"):
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    try:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
    except Exception as _sentry_err:
        pass
