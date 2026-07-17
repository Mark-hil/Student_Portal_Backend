# Backend TODOs

## 1. Docker & Deployment
- [ ] Spin up the full production stack using `docker-compose up --build`.
- [ ] Confirm Celery worker processes async email tasks correctly in the background.

## 2. Automated Testing
- [ ] Write unit tests for GPA engine (`apps.grades.gpa`) using `pytest`.
  - [ ] Test Semester GPA calculation.
  - [ ] Test Cumulative GPA calculation.
  - [ ] Test zero-credit and 0% weight assignment edge cases.
- [ ] Ensure the GitHub Actions CI pipeline (`.github/workflows/ci.yml`) passes successfully.

## 3. Export Features
- [ ] Implement PDF generation for Official Transcripts.
- [ ] Implement a CSV/Excel export for Lecturer Grade Batches.
