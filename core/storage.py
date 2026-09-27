"""Custom storage backends."""
import os
from cloudinary_storage.storage import MediaCloudinaryStorage


class DynamicCloudinaryStorage(MediaCloudinaryStorage):
    """
    Intelligently determines Cloudinary resource_type by file extension:
    - 'image' for images (jpeg, png, webp, svg, etc.)
    - 'video' for video formats (mp4, mov, webm, etc.)
    - 'raw' for documents and binaries (pdf, docx, doc, xlsx, csv, zip, etc.)
    """
    IMAGE_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff", ".tif"
    }
    VIDEO_EXTENSIONS = {
        ".mp4", ".mov", ".avi", ".webm", ".mkv", ".wmv", ".flv"
    }

    def _get_resource_type(self, name):
        ext = os.path.splitext(name)[1].lower()
        if ext in self.IMAGE_EXTENSIONS:
            return "image"
        if ext in self.VIDEO_EXTENSIONS:
            return "video"
        return "raw"
