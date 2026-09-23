from django.contrib import admin
from .models import Notification, SMSLog


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "notif_type", "title", "read", "created_at"]
    list_filter = ["notif_type", "read"]
    search_fields = ["user__email", "title"]
    raw_id_fields = ["user"]


@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    list_display = [
        "recipient_phone",
        "recipient_name",
        "purpose",
        "status",
        "provider",
        "provider_message_id",
        "sent_at",
        "delivered_at",
        "created_at",
    ]
    list_filter = ["status", "purpose", "provider", "created_at"]
    search_fields = [
        "recipient_phone",
        "recipient_name",
        "provider_message_id",
        "message_body",
        "user__email",
    ]
    readonly_fields = [
        "id", "recipient_phone", "recipient_name", "user", "message_body",
        "sender_id", "purpose", "provider", "provider_message_id",
        "status", "status_code", "gateway_response", "error_detail",
        "retries_count", "sent_at", "delivered_at", "created_at", "updated_at"
    ]
    raw_id_fields = ["user"]

    def has_add_permission(self, request):
        return False
