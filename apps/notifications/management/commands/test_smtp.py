"""Django management command to test SMTP email configuration."""
import sys
from django.core.management.base import BaseCommand
from django.core.mail import get_connection, EmailMessage
from django.conf import settings


class Command(BaseCommand):
    help = "Test SMTP email configuration by sending a verification email."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient",
            nargs="?",
            default=None,
            help="Email address of the recipient to send test email to.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Check SMTP connection and credentials without actually sending an email.",
        )

    def handle(self, *args, **options):
        recipient = options.get("recipient")
        dry_run = options.get("dry_run", False)

        backend = getattr(settings, "EMAIL_BACKEND", "")
        host = getattr(settings, "EMAIL_HOST", "")
        port = getattr(settings, "EMAIL_PORT", 587)
        use_tls = getattr(settings, "EMAIL_USE_TLS", True)
        use_ssl = getattr(settings, "EMAIL_USE_SSL", False)
        user = getattr(settings, "EMAIL_HOST_USER", "")
        password = getattr(settings, "EMAIL_HOST_PASSWORD", "")
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@asdam.edu.gh")

        self.stdout.write(self.style.MIGRATE_HEADING("=== SMTP Email Configuration ==="))
        self.stdout.write(f"EMAIL_BACKEND:       {backend}")
        self.stdout.write(f"EMAIL_HOST:          {host}")
        self.stdout.write(f"EMAIL_PORT:          {port}")
        self.stdout.write(f"EMAIL_USE_TLS:       {use_tls}")
        self.stdout.write(f"EMAIL_USE_SSL:       {use_ssl}")
        self.stdout.write(f"EMAIL_HOST_USER:     {user or '(empty)'}")
        masked_pwd = f"{password[:3]}...{password[-3:]}" if len(password) > 6 else ("(configured)" if password else "(empty)")
        self.stdout.write(f"EMAIL_HOST_PASSWORD: {masked_pwd}")
        self.stdout.write(f"DEFAULT_FROM_EMAIL:  {from_email}")
        self.stdout.write("================================")

        # Check for placeholder values
        if "your-sendgrid-api-key" in password or password == "":
            self.stdout.write(
                self.style.WARNING(
                    "\n⚠️  EMAIL_HOST_PASSWORD contains a placeholder or is empty.\n"
                    "   Update EMAIL_HOST_PASSWORD in your backend/.env file with your real provider credentials."
                )
            )

        if dry_run or not recipient:
            self.stdout.write("\nTesting SMTP connection...")
            try:
                connection = get_connection(fail_silently=False)
                connection.open()
                connection.close()
                self.stdout.write(self.style.SUCCESS("✓ Successfully established connection to SMTP server!"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Failed to connect to SMTP server: {e}"))
                sys.exit(1)
            if not recipient:
                self.stdout.write(
                    "\nTip: Pass a recipient email to send an actual message:\n"
                    "     python manage.py test_smtp your-email@domain.com"
                )
            return

        # Sending actual test message
        self.stdout.write(f"\nSending test email to: {recipient}...")
        try:
            email = EmailMessage(
                subject="[ASDAM Portal] SMTP Verification Test",
                body=(
                    "Hello,\n\n"
                    "This is an automated test message from the ASDAM Student Portal to verify "
                    "that your SMTP email configuration is functioning correctly.\n\n"
                    "Timestamp: Verified\n"
                    "System: ASDAM Academic Portal"
                ),
                from_email=from_email,
                to=[recipient],
            )
            email.send(fail_silently=False)
            self.stdout.write(self.style.SUCCESS(f"✓ Test email successfully sent to {recipient}!"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Failed to send email: {e}"))
            sys.exit(1)
