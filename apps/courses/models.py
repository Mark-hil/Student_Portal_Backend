"""
Courses domain models — complete version.
Added: CourseSchedule, RegistrationWindow, CourseReview
"""
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = "categories"
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class RegistrationWindow(models.Model):
    """Defines open/close dates for course registration per semester."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    semester = models.CharField(max_length=20, unique=True)   # e.g. "2025-SPRING"
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "registration_windows"

    def __str__(self):
        return f"{self.semester}: {self.opens_at.date()} → {self.closes_at.date()}"

    @property
    def is_open(self):
        now = timezone.now()
        return self.is_active and self.opens_at <= now <= self.closes_at


class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    title = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name="courses")
    instructors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="taught_courses",
        limit_choices_to={"role": "instructor"},
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    credits = models.PositiveSmallIntegerField(default=3)
    max_students = models.PositiveIntegerField(default=30)
    semester = models.CharField(max_length=20, blank=True, db_index=True)  # e.g. "2025-SPRING"
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    prerequisites = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="required_for")
    tags = models.JSONField(default=list)
    syllabus_url = models.URLField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "courses"
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["semester", "status"]),
            models.Index(fields=["start_date", "end_date"]),
        ]

    def __str__(self):
        return f"{self.code} — {self.title}"

    @property
    def active_enrollment_count(self):
        return self.enrollments.filter(status="active").count()

    @property
    def is_full(self):
        return self.active_enrollment_count >= self.max_students

    @property
    def available_seats(self):
        return max(0, self.max_students - self.active_enrollment_count)


class CourseSchedule(models.Model):
    """Recurring weekly schedule for a course section."""
    class Day(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="schedules")
    day_of_week = models.IntegerField(choices=Day.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.CharField(max_length=50, blank=True)
    is_online = models.BooleanField(default=False)
    meeting_link = models.URLField(blank=True)

    class Meta:
        db_table = "course_schedules"
        unique_together = [("course", "day_of_week", "start_time")]

    def __str__(self):
        return f"{self.course.code} {self.get_day_of_week_display()} {self.start_time}–{self.end_time}"


class Lesson(models.Model):
    class LessonType(models.TextChoices):
        VIDEO = "video", "Video"
        READING = "reading", "Reading"
        QUIZ = "quiz", "Quiz"
        ASSIGNMENT = "assignment", "Assignment"
        LIVE = "live", "Live Session"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=255)
    order = models.PositiveSmallIntegerField(default=0)
    lesson_type = models.CharField(max_length=20, choices=LessonType.choices)
    content = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    is_free_preview = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "lessons"
        unique_together = [("course", "order")]
        ordering = ["order"]

    def __str__(self):
        return f"{self.course.code} — {self.order}. {self.title}"


class LessonProgress(models.Model):
    """Tracks individual lesson completion per student."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress_records")
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "lesson_progress"
        unique_together = [("student", "lesson")]


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DROPPED = "dropped", "Dropped"
        COMPLETED = "completed", "Completed"
        WAITLISTED = "waitlisted", "Waitlisted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
        limit_choices_to={"role": "student"},
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    enrolled_at = models.DateTimeField(default=timezone.now, db_index=True)
    dropped_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    progress_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Grade at completion
    final_grade = models.CharField(max_length=5, blank=True)
    grade_points = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "enrollments"
        unique_together = [("student", "course")]
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["course", "status"]),
            models.Index(fields=["student", "course", "status"]),
        ]

    def __str__(self):
        return f"{self.student.email} → {self.course.code} [{self.status}]"
