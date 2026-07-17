from django.contrib import admin
from .models import UploadedFile


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display  = ["original_name", "uploaded_by", "content_type", "size_bytes", "purpose", "created_at"]
    list_filter   = ["content_type", "purpose"]
    search_fields = ["original_name", "uploaded_by__email"]
    raw_id_fields = ["uploaded_by"]
    readonly_fields = ["id", "created_at"]
