"""Custom storage backends."""
import os
import sys
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from cloudinary_storage.storage import MediaCloudinaryStorage


class DynamicCloudinaryStorage(MediaCloudinaryStorage):
    """
    Intelligently determines Cloudinary resource_type by file extension:
    - 'image' for images (jpeg, png, webp, svg, etc.)
    - 'video' for video formats (mp4, mov, webm, etc.)
    - 'raw' for documents and binaries (pdf, docx, doc, xlsx, csv, zip, etc.)
    Falls back gracefully to local FileSystemStorage in testing or offline setups.
    """
    IMAGE_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff", ".tif", ".heic", ".heif"
    }
    VIDEO_EXTENSIONS = {
        ".mp4", ".mov", ".avi", ".webm", ".mkv", ".wmv", ".flv", ".m4v"
    }
    RAW_EXTENSIONS = {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".csv", ".txt", ".rtf", ".odt", ".ods", ".odp",
        ".zip", ".rar", ".7z", ".tar", ".gz", ".json", ".xml"
    }

    def _save(self, name, content):
        cloud_name = getattr(settings, "CLOUDINARY_STORAGE", {}).get("CLOUD_NAME", "")
        if "pytest" in sys.modules or not cloud_name or cloud_name in ("dummy", "test", ""):
            return FileSystemStorage()._save(name, content)
        try:
            return super()._save(name, content)
        except Exception:
            return FileSystemStorage()._save(name, content)

    def url(self, name):
        if not name:
            return ""
        if name.startswith("http://") or name.startswith("https://"):
            return name
        cloud_name = getattr(settings, "CLOUDINARY_STORAGE", {}).get("CLOUD_NAME", "")
        if "pytest" in sys.modules or not cloud_name or cloud_name in ("dummy", "test", ""):
            return FileSystemStorage().url(name)
        if FileSystemStorage().exists(name):
            return FileSystemStorage().url(name)
        try:
            return super().url(name)
        except Exception:
            return FileSystemStorage().url(name)

    def _get_resource_type(self, name):
        ext = os.path.splitext(name)[1].lower()
        if ext in self.VIDEO_EXTENSIONS:
            return "video"
        if ext in self.RAW_EXTENSIONS:
            return "raw"
        if ext in self.IMAGE_EXTENSIONS:
            return "image"
        # Cloudinary public_ids for images have no extension, whereas raw files retain them.
        # Fall back to "image" (default for MediaCloudinaryStorage).
        return "image"
