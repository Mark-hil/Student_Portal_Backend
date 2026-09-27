FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

# Install runtime dependencies (libpq5 for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

# Collect static files for Django admin & DRF
RUN python manage.py collectstatic --noinput --settings=config.settings.base 2>/dev/null || true

# Non-root user for security
RUN addgroup --system app && adduser --system --group app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--worker-class", "gthread", "--threads", "4", "--timeout", "60"]
