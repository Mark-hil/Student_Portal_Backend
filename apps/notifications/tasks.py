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


def dispatch_welcome_notifications(user_id: str, raw_password: str):
    """
    Dispatcher for student welcome credentials.
    Sends both Email and SMS with temporary login credentials and mandatory
    onboarding instructions. Executes safely with graceful error handling.
    """
    from django.conf import settings
    from django.core.mail import send_mail
    from django.contrib.auth import get_user_model
    from .sms import send_sms
    from .models import Notification

    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error("Welcome dispatch skipped: User %s not found.", user_id)
        return {"success": False, "detail": "User not found."}

    portal_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173").rstrip("/")
    student_id = user.student_id or user.email
    full_name = user.full_name or user.first_name
    program_label = "Nursing" if user.program == "nursing" else "Midwifery" if user.program == "midwifery" else user.department or "Healthcare"

    # 1. Dispatch SMS with Portal URL and explicit Credentials
    sms_text = (
        f"ASDAM ADMISSIONS:\n"
        f"Welcome {user.first_name}!\n"
        f"Portal URL: {portal_url}\n"
        f"Student ID: {student_id}\n"
        f"Username: {user.email}\n"
        f"Temp Password: {raw_password}\n"
        f"Log in now to complete your mandatory profile registration."
    )
    sms_result = {"success": False}
    if user.phone:
        try:
            sms_result = send_sms(
                phone=user.phone,
                message=sms_text,
                sender_id="ASDAM",
                recipient_name=full_name,
                user=user,
                purpose="fresher_credentials",
            )
        except Exception as e:
            logger.error("SMS dispatch error for user %s: %s", user.email, e)

    # 2. Dispatch Email
    email_subject = f"Welcome to ASDAM Student Portal — Your Login Credentials [{student_id}]"
    text_email = (
        f"Dear {full_name},\n\n"
        f"Welcome to Arch-Bishop Porter College of Health & Allied Sciences (ASDAM)!\n"
        f"Your official student portal account has been created.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"YOUR PORTAL LOGIN CREDENTIALS\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Portal Login URL:    {portal_url}\n"
        f"Student ID:          {student_id}\n"
        f"Username / Email:    {user.email}\n"
        f"Temporary Password:  {raw_password}\n"
        f"Assigned Program:    {program_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"STEPS TO GET STARTED:\n"
        f"1. Open the portal URL in your web browser: {portal_url}\n"
        f"2. Enter your Student ID (or Email) and your Temporary Password shown above.\n"
        f"3. Complete the Mandatory Student Profile Registration (Bio, Ghana Card, Contact, and Guardian info).\n"
        f"4. Set your permanent password to unlock complete portal features (Course Registration, Results, Financials).\n\n"
        f"If you require assistance, please contact the Academic Affairs Directorate.\n\n"
        f"Best regards,\n"
        f"Academic Affairs & Admissions Directorate\n"
        f"ASDAM Student Portal"
    )

    html_email = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
        .card {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.06); }}
        .header {{ background: linear-gradient(135deg, #1e1b4b 0%, #312e81 40%, #4338ca 100%); padding: 32px 28px; text-align: center; color: #ffffff; }}
        .header h1 {{ margin: 0 0 6px; font-size: 22px; font-weight: 800; letter-spacing: -0.02em; }}
        .header p {{ margin: 0; font-size: 13.5px; opacity: 0.9; color: #c7d2fe; }}
        .content {{ padding: 28px; }}
        .cred-box {{ background: #f8fafc; border-radius: 12px; border: 1.5px solid #cbd5e1; padding: 18px 20px; margin: 22px 0; }}
        .cred-box-title {{ font-size: 12px; font-weight: 800; letter-spacing: 0.05em; color: #4338ca; text-transform: uppercase; margin-bottom: 12px; }}
        .cred-row {{ display: flex; justify-content: space-between; align-items: center; padding: 9px 0; border-bottom: 1px dashed #e2e8f0; font-size: 13.5px; }}
        .cred-row:last-child {{ border-bottom: none; }}
        .cred-label {{ color: #64748b; font-weight: 600; }}
        .cred-val {{ font-weight: 800; color: #0f172a; font-family: 'SFMono-Regular', Consolas, Menlo, monospace; font-size: 14px; word-break: break-all; }}
        .cred-url {{ color: #4338ca; text-decoration: underline; font-weight: 700; }}
        .btn {{ display: block; text-align: center; background: #4338ca; color: #ffffff !important; padding: 14px 24px; border-radius: 10px; font-weight: 700; text-decoration: none; margin: 24px 0 16px; font-size: 15px; box-shadow: 0 4px 12px rgba(67, 56, 202, 0.25); }}
        .steps {{ background: #f1f5f9; border-radius: 10px; padding: 16px 20px; margin: 18px 0; font-size: 13px; color: #334155; line-height: 1.6; }}
        .steps ol {{ margin: 8px 0 0; padding-left: 20px; }}
        .steps li {{ margin-bottom: 6px; }}
        .notice {{ background: #eff6ff; border-left: 4px solid #3b82f6; padding: 12px 16px; border-radius: 0 8px 8px 0; font-size: 13px; color: #1e40af; margin-top: 16px; }}
        .footer {{ padding: 20px 28px; background: #fafafa; border-top: 1px solid #f1f5f9; text-align: center; font-size: 11.5px; color: #94a3b8; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <h1>ASDAM Student Portal</h1>
          <p>Arch-Bishop Porter College of Health & Allied Sciences</p>
        </div>
        <div class="content">
          <p style="font-size: 15px; margin-top: 0;">Dear <strong>{full_name}</strong>,</p>
          <p style="font-size: 13.5px; line-height: 1.6; color: #475569;">
            Your student portal profile has been created for the <strong>{program_label}</strong> program. 
            Use the URL and credentials below to sign in:
          </p>

          <div class="cred-box">
            <div class="cred-box-title">&#128273; Institutional Login Credentials</div>
            <div class="cred-row">
              <span class="cred-label">Portal URL:</span>
              <span class="cred-val"><a href="{portal_url}" class="cred-url" target="_blank">{portal_url}</a></span>
            </div>
            <div class="cred-row">
              <span class="cred-label">Student ID:</span>
              <span class="cred-val" style="color: #4338ca;">{student_id}</span>
            </div>
            <div class="cred-row">
              <span class="cred-label">Username / Email:</span>
              <span class="cred-val">{user.email}</span>
            </div>
            <div class="cred-row">
              <span class="cred-label">Temporary Password:</span>
              <span class="cred-val" style="color: #b91c1c;">{raw_password}</span>
            </div>
            <div class="cred-row">
              <span class="cred-label">Program:</span>
              <span class="cred-val">{program_label}</span>
            </div>
          </div>

          <a href="{portal_url}" class="btn">Log In to Student Portal &rarr;</a>

          <div class="steps">
            <strong>Next Steps:</strong>
            <ol>
              <li>Go to <a href="{portal_url}" style="color: #4338ca;">{portal_url}</a></li>
              <li>Sign in using your <strong>Student ID</strong> (or Email) and <strong>Temporary Password</strong>.</li>
              <li>Complete the mandatory <strong>Student Profile Registration</strong> (Ghana Card, Bio, Guardian details).</li>
              <li>Choose a secure new permanent password.</li>
            </ol>
          </div>

          <div class="notice">
            <strong>Mandatory Registration Notice:</strong> Portal services (Course Registration, Semester Results, and Financials) will remain locked until your registration is submitted.
          </div>
        </div>
        <div class="footer">
          &copy; {user.created_at.year} ASDAM Institution. All rights reserved. Do not share your temporary credentials with anyone.
        </div>
      </div>
    </body>
    </html>
    """

    email_result = {"success": False}
    try:
        send_mail(
            subject=email_subject,
            message=text_email,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_email,
            fail_silently=True,
        )
        email_result = {"success": True}
        logger.info("Welcome email sent to %s for Student ID %s", user.email, student_id)
    except Exception as e:
        logger.error("Welcome email failed for %s: %s", user.email, e)

    # 3. Create In-App Notification
    try:
        Notification.objects.create(
            user=user,
            notif_type=Notification.NotifType.SYSTEM,
            title="Welcome to ASDAM Student Portal",
            body=f"Your institutional Student ID is {student_id}. Please complete your mandatory student registration at {portal_url} to unlock all portal features.",
            data={"student_id": student_id, "portal_url": portal_url, "action": "complete_registration"}
        )
    except Exception as e:
        logger.warning("Failed to create in-app notification: %s", e)

    return {
        "success": True,
        "sms": sms_result,
        "email": email_result,
    }


def dispatch_registration_confirmation(user_id: str):
    """
    Sends confirmation notification (Email & SMS) when a student finishes mandatory registration.
    """
    from django.conf import settings
    from django.core.mail import send_mail
    from django.contrib.auth import get_user_model
    from .sms import send_sms
    from .models import Notification

    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    student_id = user.student_id or user.email
    full_name = user.full_name or user.first_name

    # SMS
    if user.phone:
        try:
            sms_text = (
                f"ASDAM: Congratulations {user.first_name}! Your student registration is complete. "
                f"Full portal access is now unlocked for Student ID {student_id}."
            )
            send_sms(
                phone=user.phone,
                message=sms_text,
                sender_id="ASDAM",
                recipient_name=full_name,
                user=user,
                purpose="registration_completed",
            )
        except Exception as e:
            logger.warning("Registration confirmed SMS failed: %s", e)

    # Email
    try:
        subject = f"Registration Completed — ASDAM Student Portal [{student_id}]"
        body = (
            f"Dear {full_name},\n\n"
            f"Congratulations! Your student profile registration has been successfully verified and completed.\n"
            f"Your ASDAM Student ID is {student_id}.\n\n"
            f"All portal features — including Course Registration, Academic Results, and Financials — are now unlocked.\n\n"
            f"Best regards,\nAcademic Affairs Directorate\nASDAM Student Portal"
        )
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception as e:
        logger.warning("Registration confirmed email failed: %s", e)

    # Notification
    try:
        Notification.objects.create(
            user=user,
            notif_type=Notification.NotifType.SYSTEM,
            title="Registration Verified & Unlocked",
            body=f"Your profile registration is complete. Full portal access is unlocked for {student_id}.",
            data={"status": "registered"}
        )
    except Exception as e:
        logger.warning("Failed to create confirmed notification: %s", e)
