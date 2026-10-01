"""Notification & SMS views."""
import csv
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny, SAFE_METHODS, BasePermission
from rest_framework.exceptions import PermissionDenied
from rest_framework import serializers as drf_serializers

from apps.users.constants import normalize_role, RoleChoice
from .models import Notification, SMSLog, Announcement
from .sms import check_sms_status, resend_sms

logger = logging.getLogger(__name__)


class IsAdminOrStaffOrReadOnly(BasePermission):
    """
    Allows all authenticated users to read published announcements.
    Allows only Super Admins, Academic Officers, and Department Heads to create, edit, or delete.
    """
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        if request.user.is_superuser or request.user.is_staff:
            return True
        norm = normalize_role(request.user.role)
        return norm in (RoleChoice.SUPER_ADMIN, RoleChoice.ACADEMIC_OFFICER, RoleChoice.HEAD_OF_DEPARTMENT)


class AnnouncementSerializer(drf_serializers.ModelSerializer):
    category_display = drf_serializers.CharField(source="get_category_display", read_only=True)
    target_audience_display = drf_serializers.CharField(source="get_target_audience_display", read_only=True)
    author_name = drf_serializers.CharField(read_only=True)
    author_role = drf_serializers.CharField(read_only=True)

    class Meta:
        model = Announcement
        fields = [
            "id",
            "title",
            "content",
            "category",
            "category_display",
            "target_audience",
            "target_audience_display",
            "author",
            "author_name",
            "author_role",
            "is_pinned",
            "is_published",
            "attachment_url",
            "attachment_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "author", "author_name", "author_role", "created_at", "updated_at"]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            user = request.user
            validated_data["author"] = user
            name = user.full_name if hasattr(user, "full_name") and user.full_name else (user.get_full_name() or user.email)
            validated_data["author_name"] = name
            role_disp = user.get_role_display() if hasattr(user, "get_role_display") else user.role
            validated_data["author_role"] = role_disp
        return super().create(validated_data)


class AnnouncementViewSet(viewsets.ModelViewSet):
    """
    Official Institutional Announcements & Circulars.
    Students see notices targeted to all or students.
    Lecturers see notices targeted to all or faculty.
    Staff & Administrators see all notices and can manage them.
    """
    permission_classes = [IsAuthenticated, IsAdminOrStaffOrReadOnly]
    serializer_class = AnnouncementSerializer

    def get_queryset(self):
        user = self.request.user
        norm_role = normalize_role(user.role) if hasattr(user, "role") else RoleChoice.STUDENT

        is_admin_or_staff = (
            user.is_superuser
            or user.is_staff
            or norm_role in (RoleChoice.SUPER_ADMIN, RoleChoice.ACADEMIC_OFFICER, RoleChoice.HEAD_OF_DEPARTMENT)
        )

        qs = Announcement.objects.all()
        if not is_admin_or_staff:
            qs = qs.filter(is_published=True)
            if norm_role == RoleChoice.STUDENT:
                qs = qs.filter(
                    Q(target_audience=Announcement.TargetAudience.ALL)
                    | Q(target_audience=Announcement.TargetAudience.STUDENTS)
                )
            elif norm_role in (RoleChoice.LECTURER,):
                qs = qs.filter(
                    Q(target_audience=Announcement.TargetAudience.ALL)
                    | Q(target_audience=Announcement.TargetAudience.FACULTY)
                )
            elif norm_role in (RoleChoice.FINANCE,):
                qs = qs.filter(
                    Q(target_audience=Announcement.TargetAudience.ALL)
                    | Q(target_audience=Announcement.TargetAudience.STAFF)
                )

        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(content__icontains=search))

        return qs.order_by("-is_pinned", "-created_at")

    @action(detail=True, methods=["post"], url_path="toggle-pin")
    def toggle_pin(self, request, pk=None):
        announcement = self.get_object()
        announcement.is_pinned = not announcement.is_pinned
        announcement.save(update_fields=["is_pinned"])
        return Response({"status": "ok", "is_pinned": announcement.is_pinned})


class NotificationSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "notif_type", "title", "body", "read", "created_at", "read_at"]
        read_only_fields = ["id", "notif_type", "title", "body", "created_at"]


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

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


class SMSLogSerializer(drf_serializers.ModelSerializer):
    status_display = drf_serializers.CharField(source="get_status_display", read_only=True)
    user_email = drf_serializers.CharField(source="user.email", read_only=True)
    user_role = drf_serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = SMSLog
        fields = [
            "id", "recipient_phone", "recipient_name", "user", "user_email", "user_role",
            "message_body", "sender_id", "purpose", "provider", "provider_message_id",
            "status", "status_display", "status_code", "gateway_response", "error_detail",
            "retries_count", "sent_at", "delivered_at", "created_at", "updated_at"
        ]
        read_only_fields = fields


class SMSLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Super-Admin & Auditor endpoint for telecom delivery tracking.
    Enforces that only Super Administrators or auditors can inspect SMS logs.
    """
    serializer_class = SMSLogSerializer

    def get_permissions(self):
        if self.action == "webhook":
            return [AllowAny()]
        return [IsAuthenticated()]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.action != "webhook":
            user = request.user
            is_super = getattr(user, "is_super_admin", False) or getattr(user, "role", "") in ("super_admin", "super-admin")
            has_audit_func = "audit.view_logs" in getattr(user, "effective_functions", [])
            if not (is_super or has_audit_func):
                raise PermissionDenied("Access restricted: Only Super Administrators and compliance auditors may view SMS logs.")

    def get_queryset(self):
        qs = SMSLog.objects.all().select_related("user").order_by("-created_at")
        params = self.request.query_params

        status_param = params.get("status")
        if status_param and status_param != "all":
            qs = qs.filter(status=status_param.upper())

        purpose_param = params.get("purpose")
        if purpose_param and purpose_param != "all":
            qs = qs.filter(purpose=purpose_param)

        search_param = params.get("search")
        if search_param:
            qs = qs.filter(
                Q(recipient_phone__icontains=search_param) |
                Q(recipient_name__icontains=search_param) |
                Q(provider_message_id__icontains=search_param) |
                Q(purpose__icontains=search_param) |
                Q(message_body__icontains=search_param)
            )

        start_date = params.get("start_date")
        if start_date:
            qs = qs.filter(created_at__gte=start_date)

        end_date = params.get("end_date")
        if end_date:
            qs = qs.filter(created_at__lte=end_date)

        return qs

    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """Aggregate telecom KPIs."""
        total = SMSLog.objects.count()
        delivered = SMSLog.objects.filter(status=SMSLog.DeliveryStatus.DELIVERED).count()
        submitted = SMSLog.objects.filter(status=SMSLog.DeliveryStatus.SUBMITTED).count()
        pending_approval = SMSLog.objects.filter(status=SMSLog.DeliveryStatus.PENDING_APPROVAL).count()
        failed = SMSLog.objects.filter(status__in=[SMSLog.DeliveryStatus.FAILED, SMSLog.DeliveryStatus.REJECTED]).count()
        simulated = SMSLog.objects.filter(status=SMSLog.DeliveryStatus.SIMULATED).count()

        since_24h = timezone.now() - timedelta(hours=24)
        last_24h_count = SMSLog.objects.filter(created_at__gte=since_24h).count()
        delivered_rate = round((delivered / total * 100), 1) if total > 0 else 0.0

        return Response({
            "total_sms": total,
            "delivered": delivered,
            "submitted": submitted,
            "pending_approval": pending_approval,
            "failed": failed,
            "simulated": simulated,
            "delivered_rate_pct": delivered_rate,
            "last_24h_count": last_24h_count,
        })

    @action(detail=True, methods=["post"], url_path="check-status")
    def check_status(self, request, pk=None):
        """Polls Arkesel API for refreshed carrier delivery status."""
        log = self.get_object()
        result = check_sms_status(log)
        log.refresh_from_db()
        return Response({
            "status": "success" if result.get("success") else "warning",
            "delivery_result": result,
            "log": self.get_serializer(log).data
        })

    @action(detail=True, methods=["post"], url_path="resend")
    def resend(self, request, pk=None):
        """Re-dispatches an SMS."""
        log = self.get_object()
        result = resend_sms(log)
        log.refresh_from_db()
        return Response({
            "status": "success" if result.get("success") else "failed",
            "dispatch_result": result,
            "log": self.get_serializer(log).data
        })

    @action(detail=False, methods=["get"], url_path="export-csv")
    def export_csv(self, request):
        """Streams CSV telecom report."""
        qs = self.filter_queryset(self.get_queryset())
        timestamp_str = timezone.now().strftime("%Y%m%d_%H%M")
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="asdam_sms_delivery_log_{timestamp_str}.csv"'
        response.write("\ufeff")

        writer = csv.writer(response)
        writer.writerow(["ASDAM INSTITUTIONAL TELECOM & SMS DISPATCH LEDGER"])
        writer.writerow(["Exported At", timezone.now().strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Total Records", qs.count()])
        writer.writerow([])
        writer.writerow([
            "Log ID", "Recipient Phone", "Recipient Name", "User Email",
            "Sender ID", "Purpose", "Provider", "Provider Msg ID",
            "Status", "Status Code", "Retries", "Sent At", "Delivered At", "Created At",
            "Error Detail", "Message Body"
        ])

        for item in qs.iterator(chunk_size=500):
            writer.writerow([
                str(item.id),
                item.recipient_phone,
                item.recipient_name,
                getattr(item.user, "email", "N/A"),
                item.sender_id,
                item.purpose,
                item.provider,
                item.provider_message_id or "N/A",
                item.status,
                item.status_code or "",
                item.retries_count,
                item.sent_at.strftime("%Y-%m-%d %H:%M:%S") if item.sent_at else "",
                item.delivered_at.strftime("%Y-%m-%d %H:%M:%S") if item.delivered_at else "",
                item.created_at.strftime("%Y-%m-%d %H:%M:%S") if item.created_at else "",
                item.error_detail or "",
                item.message_body
            ])

        return response

    @action(detail=False, methods=["post"], url_path="webhook")
    def webhook(self, request):
        """
        Public webhook endpoint for Arkesel Delivery Receipts (DLR).
        Receives carrier callbacks and updates the corresponding SMSLog.
        """
        data = request.data or {}
        msg_id = (
            data.get("id")
            or data.get("ID")
            or data.get("message_id")
            or data.get("sms_id")
            or request.query_params.get("id")
        )

        if not msg_id:
            return Response({"status": "ignored", "detail": "Missing message ID."}, status=status.HTTP_400_BAD_REQUEST)

        carrier_status = str(data.get("status") or "").upper()
        logger.info("📩 [Arkesel DLR Webhook] Msg ID: %s | Status: %s", msg_id, carrier_status)

        try:
            log = SMSLog.objects.get(provider_message_id=str(msg_id))
            if carrier_status in ("DELIVERED", "SUCCESSFUL"):
                log.status = SMSLog.DeliveryStatus.DELIVERED
                log.delivered_at = timezone.now()
            elif carrier_status in ("FAILED", "UNDELIVERED", "REJECTED", "EXPIRED"):
                log.status = SMSLog.DeliveryStatus.FAILED
            elif carrier_status in ("SUBMITTED", "QUEUED"):
                log.status = SMSLog.DeliveryStatus.SUBMITTED

            log.gateway_response = {**(log.gateway_response or {}), "webhook_dlr": data}
            log.save(update_fields=["status", "delivered_at", "gateway_response", "updated_at"])
            return Response({"status": "updated", "id": str(log.id), "delivery_status": log.status})
        except SMSLog.DoesNotExist:
            logger.warning("Arkesel DLR message ID %s not found in database.", msg_id)
            return Response({"status": "not_found", "message_id": msg_id}, status=status.HTTP_200_OK)
