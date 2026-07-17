# UniPortal — Student Portal (Backend)

The backend API for the UniPortal student portal, built with **Django 5 + DRF**.

## Features
- **Core API** — RESTful endpoints for courses, users, and grades
- **GPA Engine** — Semester & Cumulative GPA computed per term from weighted scores, auto-updated upon grade publication
- **Notifications** — Celery async email tasks
- **File uploads** — S3-backed with MIME + size validation
- **JWT auth** — 15-min access token, 7-day rotating refresh, blacklist on logout

## Project structure
```
backend/
├── apps/
│   ├── users/          # Custom user model, auth views
│   ├── courses/        # Course catalog, enrollment, registration service
│   ├── grades/         # Grades, GPA engine, transcript, Celery tasks
│   ├── notifications/  # Notification model + async email tasks
│   └── files/          # S3 file upload
├── config/             # Settings (base/dev/prod), URLs, Celery, WSGI
├── core/               # Pagination, exceptions, permissions, middleware, DB router
├── manage.py
└── requirements.txt
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export DJANGO_SETTINGS_MODULE=config.settings.development
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver        # → http://localhost:8000
```

### Docker
```bash
docker-compose up --build
```
