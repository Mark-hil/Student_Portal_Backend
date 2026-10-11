"""
Audit Service Module.
Provides centralized, defensive, and structured audit event logging.
Guarantees fail-safe execution so that logging issues never interrupt
primary business operations while strictly maintaining tamper-evident audit trails.
"""
import sys
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Any, Dict
import logging
from django.utils import timezone
from apps.users.models import AuditLog

logger = logging.getLogger("apps.audit")

_audit_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="audit_writer")
atexit.register(lambda: _audit_executor.shutdown(wait=False))


def _async_persist_audit_log(entry_kwargs: Dict[str, Any], actor_id: Optional[str]) -> None:
    from django.db import connection
    try:
        if actor_id:
            from apps.users.models import User
            actor = User.objects.filter(pk=actor_id).first()
            entry_kwargs["actor"] = actor
        AuditLog.objects.create(**entry_kwargs)
    except Exception as exc:
        logger.exception("Async audit log write failed: %s", exc)
    finally:
        connection.close()


class AuditService:
    @staticmethod
    def get_client_ip(request) -> Optional[str]:
        if not request:
            return None
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")

    @staticmethod
    def get_user_agent(request) -> str:
        if not request:
            return ""
        return str(request.META.get("HTTP_USER_AGENT", ""))[:500]

    @classmethod
    def log_event(
        cls,
        action: str,
        category: str = AuditLog.Category.SYSTEM,
        actor: Optional[Any] = None,
        actor_email: str = "",
        actor_role: str = "",
        request: Optional[Any] = None,
        status: str = AuditLog.Status.SUCCESS,
        target_type: str = "",
        target_id: str = "",
        target_repr: str = "",
        description: str = "",
        changes: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        async_write: Optional[bool] = None,
    ) -> Optional[AuditLog]:
        """
        Record an immutable audit log entry with complete attribution and fail-safe error handling.
        Dispatches to a background worker thread by default for zero HTTP latency impact.
        """
        try:
            # Derive actor information if request is provided
            if request and hasattr(request, "user") and request.user and request.user.is_authenticated:
                if not actor:
                    actor = request.user

            if actor:
                actor_email = actor_email or getattr(actor, "email", "")
                actor_role = actor_role or getattr(actor, "normalized_role", getattr(actor, "role", ""))

            resolved_ip = ip_address or cls.get_client_ip(request)
            user_agent = cls.get_user_agent(request)

            meta_payload = metadata.copy() if metadata else {}
            if request:
                if "path" not in meta_payload and hasattr(request, "path"):
                    meta_payload["path"] = request.path
                if "method" not in meta_payload and hasattr(request, "method"):
                    meta_payload["method"] = request.method
                if "request_id" not in meta_payload:
                    meta_payload["request_id"] = request.META.get("X_REQUEST_ID") or request.META.get("HTTP_X_REQUEST_ID", "")

            # If not explicitly specified, default to async unless running under pytest
            if async_write is None:
                async_write = "pytest" not in sys.modules

            actor_id = str(actor.pk) if (actor and hasattr(actor, "pk")) else None
            entry_kwargs = {
                "timestamp": timezone.now(),
                "actor": actor if (not async_write and actor and hasattr(actor, "pk")) else None,
                "actor_email": actor_email or "Anonymous",
                "actor_role": actor_role or "anonymous",
                "ip_address": resolved_ip,
                "user_agent": user_agent,
                "action": action,
                "action_category": category,
                "status": status,
                "target_type": target_type,
                "target_id": str(target_id),
                "target_repr": str(target_repr)[:255],
                "description": description,
                "changes": changes or {},
                "metadata": meta_payload,
            }

            if async_write:
                _audit_executor.submit(_async_persist_audit_log, entry_kwargs, actor_id)
                logger.info(
                    "Audit (async): [%s] %s by %s on %s - %s",
                    category, action, actor_email, target_repr, status
                )
                return None

            audit_entry = AuditLog.objects.create(**entry_kwargs)
            logger.info(
                "Audit: [%s] %s by %s on %s - %s",
                category, action, actor_email, target_repr, status
            )
            return audit_entry
        except Exception as exc:
            # Defensive auditor rule: never crash calling transaction
            logger.exception("Failed to write audit log for action %s: %s", action, exc)
            return None
