"""Notification views."""
import logging
from django.utils import timezone
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers as drf_serializers
from .models import Notification

logger = logging.getLogger(__name__)


class NotificationSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model  = Notification
        fields = ["id", "notif_type", "title", "body", "read", "created_at", "read_at"]
        read_only_fields = ["id", "notif_type", "title", "body", "created_at"]


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")

    @action(detail=True, methods=["patch"], url_path="read")
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        notif.mark_read()
        return Response({"status": "read"})

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(read=False).update(
            read=True, read_at=timezone.now()
        )
        logger.info("Marked %d notifications read for %s", updated, request.user.email)
        return Response({"status": "ok", "updated": updated})

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = self.get_queryset().filter(read=False).count()
        return Response({"unread": count})
