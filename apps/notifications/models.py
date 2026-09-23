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


class SMSLog(models.Model):
    """
    Persistent telecommunication log for all SMS dispatches (Arkesel v2 API & simulated).
    Tracks real-time delivery status, handset confirmation, message IDs, and error diagnostics.
    """
    class DeliveryStatus(models.TextChoices):
        PENDING          = "PENDING",           "Pending"
        SUBMITTED        = "SUBMITTED",         "Submitted / Queued"
        DELIVERED        = "DELIVERED",         "Delivered"
        PENDING_APPROVAL = "PENDING_APPROVAL",  "Pending Approval"
        FAILED           = "FAILED",            "Failed"
        REJECTED         = "REJECTED",          "Rejected"
        SIMULATED        = "SIMULATED",         "Simulated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient_phone = models.CharField(max_length=32, db_index=True)
    recipient_name = models.CharField(max_length=255, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_logs"
    )
    message_body = models.TextField()
    sender_id = models.CharField(max_length=30, default="ASDAM")
    purpose = models.CharField(max_length=64, blank=True, default="general", db_index=True)
    provider = models.CharField(max_length=32, default="Arkesel")
    provider_message_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    status = models.CharField(
        max_length=30,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True
    )
    status_code = models.IntegerField(null=True, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)
    error_detail = models.TextField(blank=True, default="")
    retries_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sms_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["recipient_phone", "created_at"]),
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self):
        return f"[SMS {self.status}] {self.recipient_phone} ({self.recipient_name or 'N/A'}) - {self.purpose}"
