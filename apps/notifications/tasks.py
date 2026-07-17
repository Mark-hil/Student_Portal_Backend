"""Async notification tasks via Celery."""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_notification(self, user_id: str, subject: str, body: str, html_body: str = None):
    from django.core.mail import send_mail
    from django.conf import settings
    from django.contrib.auth import get_user_model
    try:
        user = get_user_model().objects.get(id=user_id)
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_body,
            fail_silently=False,
        )
        logger.info("Email sent to %s: %s", user.email, subject)
    except Exception as exc:
        logger.error("Email failed for user %s: %s", user_id, exc)
        raise self.retry(exc=exc)


@shared_task
def create_notification(user_id: str, notif_type: str, title: str, body: str, data: dict = None):
    from .models import Notification
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    Notification.objects.create(
        user_id=user_id,
        notif_type=notif_type,
        title=title,
        body=body,
        data=data or {},
    )
    
    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {
                "type": "notification_message",
                "message": {
                    "title": title,
                    "body": body,
                    "notif_type": notif_type,
                    "data": data or {}
                }
            }
        )
        
    logger.debug("Notification created for user %s: %s", user_id, title)
