# UniPortal — Backend API

The backend API for the S.D.A NMTC Asamang - AgonaManagement & Student Information System, built with **Django 5 + Django REST Framework**, **Neon Serverless PostgreSQL**, **Cloudinary**, and **Celery**.

---

## 🌟 Key Features

- **Multi-Role Institutional RBAC** — Six institutional roles (`super_admin`, `academic_officer`, `head_of_department`, `finance`, `lecturer`, `student`) with automatic input normalization for legacy aliases (`admin`, `staff`, `instructor`, etc.).
- **Neon Serverless PostgreSQL** — Fully compatible with Neon connection pooling (`-pooler`), automatic connection health checks (`conn_health_checks=True`), and zero-crash replica mirroring.
- **Cloudinary Media Storage** — Dynamic storage engine (`DynamicCloudinaryStorage`) automatically categorizing avatars/images (`image`), video lessons (`video`), and student assignment documents (`raw` for PDF, DOCX, XLSX).
- **Automated GPA Engine** — Real-time semester GPA and cumulative GPA computation upon grade batch publishing with 4.0 scale conversions.
- **Financials / Bursar** — Student fee structures, invoice generation, payment transaction logs, and printable receipts.
- **Multi-Channel Notifications & OTP** — Asynchronous Celery tasks for transactional emails (SendGrid / SMTP) and SMS OTP verification via **Arkesel (Ghana)**.
- **Security Audit Logs** — Immutable security logging for failed authentication attempts, role updates, password changes, and grade submissions.
- **Super-Admin Shielding** — Architectural protection against accidental deletion or unauthorized role manipulation of root system administrators.

---

## 🏗️ Project Architecture

```text
backend/
├── apps/
│   ├── users/           # Custom user model, RBAC, profiles, audit logging, password reset OTP
│   ├── courses/         # Course catalog, bulk registration, schedule conflict checker, deadlines
│   ├── grades/          # Assignments, student submissions, batch CSV/XLSX uploads, GPA engine
│   ├── financials/      # Fee structures, semester invoices, student payment ledger
│   ├── notifications/   # In-app notifications & Celery email/SMS delivery tasks
│   └── files/           # Media upload endpoints backed by Cloudinary
├── config/              # Base, Development, and Production settings, Celery, WSGI, ASGI
├── core/                # Custom storage, Permissions, Pagination, DB router, Middleware
├── manage.py
└── requirements.txt
```

---

## 🚀 Getting Started

### Local Development Setup

1. **Create virtual environment and install dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. **Configure environment variables**:
   ```bash
   cp .env.example .env
   ```
   *Edit `.env` with your Neon database URL, Cloudinary credentials, and secret key.*

3. **Apply database migrations**:
   ```bash
   # Development (SQLite)
   python manage.py migrate

   # Production (Neon PostgreSQL)
   export DJANGO_SETTINGS_MODULE=config.settings.production
   python manage.py migrate
   ```

4. **Create a superuser**:
   ```bash
   python manage.py createsuperuser
   ```

5. **Start the development server**:
   ```bash
   python manage.py runserver
   ```
   Server will start at `http://127.0.0.1:8000`.

---

## 🐳 Docker Deployment

The backend provides a standalone Docker Compose configuration connecting directly to **Neon** and **Cloudinary**:

```bash
# Start API, Celery Worker, Celery Beat, and Redis
docker compose up -d --build

# Run migrations on Neon from inside container
docker compose exec api python manage.py migrate

# Create super-admin inside container
docker compose exec api python manage.py createsuperuser
```

---

## 🔑 Key API Endpoints

### Authentication & Profiles
| Method | URL | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/auth/login/` | Obtain JWT access & refresh tokens |
| `POST` | `/api/v1/auth/logout/` | Blacklist active refresh token |
| `POST` | `/api/v1/auth/password-reset/request-otp/` | Send password reset OTP via SMS / Email |
| `POST` | `/api/v1/auth/password-reset/verify-otp/` | Verify OTP code & reset password |
| `GET/PATCH` | `/api/v1/users/me/` | View / update authenticated user profile |
| `POST` | `/api/v1/users/me/avatar/` | Upload profile avatar directly to Cloudinary |

### User Management & Administration
| Method | URL | Access | Description |
| :--- | :--- | :--- | :--- |
| `GET/POST` | `/api/v1/users/admin/` | Super Admin | List, filter, and create users with institutional roles |
| `GET/PATCH` | `/api/v1/users/admin/{id}/` | Super Admin | Inspect / edit user roles and metadata |
| `DELETE` | `/api/v1/users/admin/{id}/` | Super Admin | Soft-deactivate or permanently delete account |
| `GET` | `/api/v1/users/admin/audit-logs/` | Super Admin | Query immutable system audit logs |

### Course Management & Enrollment
| Method | URL | Access | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/courses/` | Authenticated | Browse course catalog with department/level filters |
| `GET` | `/api/v1/courses/my-courses/` | Student / Lecturer | List courses enrolled or assigned to instruct |
| `POST` | `/api/v1/courses/{id}/register/` | Student | Register for a single course with prerequisite checks |
| `POST` | `/api/v1/courses/bulk-register/` | Student | Register for multiple courses in a single atomic transaction |
| `GET` | `/api/v1/courses/{id}/check-conflict/` | Student | Verify timetable conflicts against current schedule |
| `POST` | `/api/v1/courses/enrollments/{id}/drop/` | Student | Drop an enrolled course |
| `GET/POST` | `/api/v1/courses/admin/registration-window/` | Academic Officer | View and open/close registration windows |

### Grades, Assignments & GPA Engine
| Method | URL | Access | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/grades/` | Student | View published grades |
| `GET` | `/api/v1/grades/gpa-summary/` | Student | Retrieve Semester GPA and Cumulative GPA |
| `GET` | `/api/v1/grades/transcript/` | Student / Officer | Official academic transcript grouped by semester |
| `POST` | `/api/v1/grades/assignments/` | Lecturer | Create course assignment |
| `POST` | `/api/v1/grades/assignments/{id}/submit/` | Student | Submit assignment file or text |
| `POST` | `/api/v1/grades/batches/{id}/upload/` | Lecturer | Batch score upload via CSV or Excel (.xlsx) |
| `PATCH` | `/api/v1/grades/batches/{id}/submit/` | Lecturer | Submit grade batch for departmental review |
| `PATCH` | `/api/v1/grades/batches/{id}/approve/` | Officer / HOD | Approve reviewed grade batch |
| `PATCH` | `/api/v1/grades/batches/{id}/publish/` | Academic Officer | Publish batch to students & trigger async GPA recomputation |

### Financials & Bursar
| Method | URL | Access | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/financials/my-invoices/` | Student | View semester fee breakdown and balance |
| `POST` | `/api/v1/financials/payments/` | Student / Finance | Record payment transaction |
| `GET` | `/api/v1/financials/receipts/{id}/` | Authenticated | Download payment receipt |
| `GET/POST` | `/api/v1/financials/admin/fee-structures/` | Finance Officer | Configure semester tuition and levies |

---

## 🧪 Automated Testing

UniPortal backend includes an extensive automated test suite with over **97 tests** covering RBAC, audit logging, GPA calculations, course conflicts, and super-admin shielding.

Run tests with coverage:
```bash
pytest --cov=apps
```
