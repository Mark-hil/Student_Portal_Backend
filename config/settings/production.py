"""Production settings."""
import os
import sentry_sdk
from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME":     os.environ["DB_NAME"],
        "USER":     os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST":     os.environ["DB_HOST"],
        "PORT":     os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": "require"},
    },
    "replica": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME":     os.environ["DB_NAME"],
        "USER":     os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST":     os.environ.get("DB_REPLICA_HOST", os.environ["DB_HOST"]),
        "PORT":     os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "TEST": {"MIRROR": "default"},
    },
}
DATABASE_ROUTERS = ["core.db_router.PrimaryReplicaRouter"]

# Security
SECURE_SSL_REDIRECT             = True
SECURE_HSTS_SECONDS             = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS  = True
SECURE_HSTS_PRELOAD             = True
SECURE_CONTENT_TYPE_NOSNIFF     = True
SESSION_COOKIE_SECURE           = True
CSRF_COOKIE_SECURE              = True
X_FRAME_OPTIONS                 = "DENY"
SECURE_PROXY_SSL_HEADER         = ("HTTP_X_FORWARDED_PROTO", "https")

# CORS
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "").split(",")
CORS_ALLOW_CREDENTIALS = True

# S3 Storage
DEFAULT_FILE_STORAGE    = "storages.backends.s3boto3.S3Boto3Storage"
STATICFILES_STORAGE     = "storages.backends.s3boto3.S3StaticStorage"
AWS_ACCESS_KEY_ID       = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY   = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME      = os.environ.get("AWS_S3_REGION_NAME", "us-east-1")
AWS_DEFAULT_ACL         = "private"
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_QUERYSTRING_AUTH    = True
AWS_QUERYSTRING_EXPIRE  = 3600
AWS_S3_FILE_OVERWRITE   = False

# Sentry
SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
