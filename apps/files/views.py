"""File upload endpoint — type + size validated, stored on S3 in production."""
import logging
from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers as drf_serializers
from .models import UploadedFile

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


class UploadedFileSerializer(drf_serializers.ModelSerializer):
    url = drf_serializers.SerializerMethodField()

    class Meta:
        model  = UploadedFile
        fields = ["id", "original_name", "content_type", "size_bytes", "url", "created_at"]

    def get_url(self, obj):
        request = self.context.get("request")
        if obj.file and hasattr(obj.file, 'url'):
            return request.build_absolute_uri(obj.file.url) if request else obj.file.url
        return None


class FileUploadView(generics.CreateAPIView):
    """POST /api/v1/files/upload/ — multipart file upload."""
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]
    serializer_class   = UploadedFileSerializer

    def create(self, request, *args, **kwargs):
        file = request.FILES.get("file")
        if not file:
            return Response({"error": "no_file", "detail": "No file provided."}, status=400)
        if file.size > MAX_SIZE_BYTES:
            return Response({"error": "file_too_large", "detail": f"Max size is {MAX_SIZE_BYTES // 1024 // 1024} MB."}, status=400)
        if file.content_type not in ALLOWED_TYPES:
            return Response({"error": "unsupported_type", "detail": f"{file.content_type} is not allowed."}, status=400)

        obj = UploadedFile.objects.create(
            uploaded_by=request.user,
            file=file,
            original_name=file.name,
            content_type=file.content_type,
            size_bytes=file.size,
            purpose=request.data.get("purpose", ""),
        )
        logger.info("Upload: %s by %s (%d bytes)", file.name, request.user.email, file.size)
        serializer = self.get_serializer(obj, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
