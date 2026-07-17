"""File upload model."""
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class UploadedFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="uploads/%Y/%m/%d/")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField()
    purpose = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "uploaded_files"
