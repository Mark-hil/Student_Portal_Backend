"""Development settings — local machine."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

CORS_ALLOW_ALL_ORIGINS = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FILE_STORAGE  = "django.core.files.storage.FileSystemStorage"
STATICFILES_STORAGE   = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Synchronous task execution in dev (no Celery needed)
CELERY_TASK_ALWAYS_EAGER = True

# Use InMemoryChannelLayer for WebSockets in development (no Redis needed)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}
