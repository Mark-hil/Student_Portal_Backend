# Project TODOs

## 1. Docker & Deployment
- [ ] Spin up the full production stack using `docker-compose up --build`.
- [ ] Verify Nginx reverse proxy routes traffic correctly.
- [ ] Test WebSocket connections through Nginx.
- [ ] Confirm Celery worker processes async email tasks correctly in the background.

## 2. Automated Testing
- [ ] Write unit tests for GPA engine (`apps.grades.gpa`) using `pytest`.
  - [ ] Test Semester GPA calculation.
  - [ ] Test Cumulative GPA calculation.
  - [ ] Test zero-credit and 0% weight assignment edge cases.
- [ ] Ensure the GitHub Actions CI pipeline (`.github/workflows/ci.yml`) passes successfully.

## 3. Export Features
- [ ] Implement PDF generation for Official Transcripts on the backend.
- [ ] Add a "Download Transcript" button to the Student Grades dashboard.
- [ ] Implement a CSV/Excel export for Lecturer Grade Batches.

## 4. Advanced Frontend Polish
- [ ] Implement a system-wide Dark Mode toggle.
- [ ] Refine mobile responsiveness for dashboards (hide sidebar, make tables scrollable on small screens).
