"""Notification model — supports all event types across the result publication workflow."""
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Notification(models.Model):
    class NotifType(models.TextChoices):
        # Student events
        GRADE_POSTED          = "grade_posted",           "Grade Posted"
        ENROLLMENT_CONFIRMED  = "enrollment_confirmed",   "Enrollment Confirmed"
        ASSIGNMENT_DUE        = "assignment_due",         "Assignment Due"
        # Lecturer events
        GRADE_BATCH_APPROVED  = "grade_batch_approved",   "Grade Batch Approved"
        GRADE_BATCH_REJECTED  = "grade_batch_rejected",   "Grade Batch Rejected"
        GRADE_BATCH_PUBLISHED = "grade_batch_published",  "Grade Batch Published"
        # Officer events
        GRADE_REVIEW_REQUESTED = "grade_review_requested","Grade Review Requested"
        # General
        ANNOUNCEMENT          = "announcement",           "Announcement"
        SYSTEM                = "system",                 "System"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    notif_type = models.CharField(max_length=30, choices=NotifType.choices, db_index=True)
    title      = models.CharField(max_length=255)
    body       = models.TextField()
    data       = models.JSONField(default=dict)
    read       = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        indexes  = [models.Index(fields=["user", "read", "created_at"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.notif_type}] {self.user.email}: {self.title}"

    def mark_read(self):
        if not self.read:
            self.read    = True
            self.read_at = timezone.now()
            self.save(update_fields=["read", "read_at"])
