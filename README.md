# UniPortal — Student Portal

Full-stack student portal built with **React 18 + TypeScript** (frontend) and **Django 5 + DRF** (backend).

## Features
- **Course Registration** — single and bulk enroll, prerequisite checks, credit-limit guard, waitlist
- **Lecturer Grading Workflow** — create assignments, batch grade uploads via CSV/XLSX with browser-based parsing
- **Officer Publishing Workflow** — review, approve, and publish grade batches to students
- **Semester & Cumulative GPA** — computed per term from weighted scores, auto-updated upon grade publication
- **Grades & Transcript** — per-assignment grades, official transcript grouped by semester
- **Notifications** — real-time WebSockets, in-app bell, and async email via Celery
- **File uploads** — S3-backed with MIME + size validation
- **JWT auth** — 15-min access token, 7-day rotating refresh, blacklist on logout

## Project structure
```
student-portal/
├── backend/
│   ├── apps/
│   │   ├── users/          # Custom user model, auth views
│   │   ├── courses/        # Course catalog, enrollment, registration service
│   │   ├── grades/         # Grades, GPA engine, transcript, Celery tasks
│   │   ├── notifications/  # Notification model + async email tasks
│   │   └── files/          # S3 file upload
│   ├── config/             # Settings (base/dev/prod), URLs, Celery, WSGI
│   ├── core/               # Pagination, exceptions, permissions, middleware, DB router
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/            # Axios client (JWT auto-refresh) + typed services
│       ├── features/       # App features
│       │   ├── admin/      # Admin dashboard, Course & User management
│       │   ├── lecturer/   # Lecturer dashboard, Assignments, Grade uploads
│       │   ├── student/    # Student dashboard, Registration, Transcripts
│       │   └── shared/     # Shared components (e.g., GradeBatchList)
│       ├── hooks/          # useAuth, useCourses, useGrades (React Query)
│       ├── store/          # Zustand auth store (persisted)
│       └── types/          # All TypeScript interfaces
├── nginx/                  # nginx.conf + portal.conf (TLS, gzip, rate limits)
├── docker-compose.yml      # Postgres, Redis, Django×2, Celery, Nginx
└── .env.example
```

## Quick start

### 1. Local development
```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
export DJANGO_SETTINGS_MODULE=config.settings.development
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver        # → http://localhost:8000

# Frontend (new terminal)
cd frontend
npm install
echo "VITE_API_URL=http://localhost:8000/api/v1" > .env.local
npm run dev                       # → http://localhost:3000
```

### 2. Docker (full stack)
```bash
cp .env.example .env    # fill in all values
docker compose up --build
# → http://localhost  (nginx serves React + proxies /api to Django)
```

## Key API endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/v1/auth/register/` | Register, returns JWT |
| POST | `/api/v1/auth/login/` | Login, returns JWT |
| POST | `/api/v1/auth/logout/` | Blacklist refresh token |
| GET/PATCH | `/api/v1/users/me/` | Profile |
| GET | `/api/v1/courses/` | Course catalog |
| GET | `/api/v1/courses/my-courses/` | Enrolled courses |
| POST | `/api/v1/courses/{id}/register/` | Single-course registration |
| POST | `/api/v1/courses/bulk-register/` | Register multiple courses |
| GET | `/api/v1/courses/{id}/check-conflict/` | Schedule conflict check |
| POST | `/api/v1/courses/enrollments/{id}/drop/` | Drop a course |
| GET | `/api/v1/grades/` | My grades |
| GET | `/api/v1/grades/gpa-summary/` | Semester GPA + Cumulative GPA |
| GET | `/api/v1/grades/transcript/` | Official transcript by semester |
| GET | `/api/v1/grades/course-summary/` | Current grade per course |
| POST | `/api/v1/grades/batches/{id}/upload/` | Batch grade upload (CSV/XLSX) |
| PATCH | `/api/v1/grades/batches/{id}/submit/` | Submit batch for review |
| PATCH | `/api/v1/grades/batches/{id}/approve/` | Officer: Approve batch |
| PATCH | `/api/v1/grades/batches/{id}/publish/` | Officer: Publish batch |
| GET | `/api/v1/notifications/` | Notifications list |
| POST | `/api/v1/notifications/mark-all-read/` | Mark all read |
| POST | `/api/v1/files/upload/` | Upload file (multipart) |
| GET | `/health/` | Health check |

## GPA calculation

```
Semester GPA  = Σ(grade_points × credits) / Σ(credits)   [one term]
Cumulative GPA = Σ(grade_points × credits) / Σ(credits)   [all terms]
```

Grade points scale: A/A+ = 4.0, A- = 3.7, B+ = 3.3, B = 3.0 … F = 0.0

Recomputed automatically via `GradeBatch.publish()` → `recompute_gpa_for_student` Celery task
whenever an Academic Officer publishes a grade batch to students.
