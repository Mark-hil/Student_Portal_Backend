"""
SMS Dispatch Service — Powered by Arkesel (https://arkesel.com).
Implements the official Arkesel SMS API v2 for reliable, high-deliverability SMS across Ghana
and international destinations.
Includes automatic Ghana phone normalization (e.g. 0241234567 -> 233241234567).
Persists all dispatch attempts and real-time carrier delivery receipts in the SMSLog database table.
Gracefully falls back to console simulation if ARKESEL_API_KEY is not configured.
"""
import os
import re
import uuid
import json
import logging
import requests
from typing import Optional, Dict, Any, List, Union
from django.utils import timezone

logger = logging.getLogger(__name__)

ARKESEL_V2_URL = "https://sms.arkesel.com/api/v2/sms/send"


def normalize_arkesel_phone(raw_phone: str) -> str:
    """
    Normalizes a phone number into Arkesel's expected recipient format.
    Arkesel expects country code without '+' (e.g. 233241234567 for Ghana).
    """
    if not raw_phone:
        return ""

    cleaned = re.sub(r"[^\d]", "", str(raw_phone).strip())

    # If it starts with 0 and has 10 digits (Ghana standard 024..., 050...)
    if cleaned.startswith("0") and len(cleaned) == 10:
        return "233" + cleaned[1:]

    # 9-digit local number without 0 (e.g. 241234567)
    if len(cleaned) == 9 and cleaned.startswith(("2", "5")):
        return "233" + cleaned

    # If already starting with 233
    if cleaned.startswith("233"):
        return cleaned

    # Already formatted international without +
    return cleaned


def normalize_phone_number(raw_phone: str) -> str:
    """
    Standard international format with leading + (e.g. +233241234567).
    """
    arkesel_num = normalize_arkesel_phone(raw_phone)
    if arkesel_num:
        return "+" + arkesel_num
    return ""


def send_sms(
    phone: str,
    message: str,
    sender_id: Optional[str] = None,
    recipient_name: Optional[str] = None,
    user: Optional[Any] = None,
    purpose: Optional[str] = "general",
) -> Dict[str, Any]:
    """
    Sends an SMS via the official Arkesel SMS API v2 and records persistent SMSLog.
    
    Configuration (via environment variables or settings):
    - ARKESEL_API_KEY: Your Arkesel API Key from https://sms.arkesel.com
    - ARKESEL_SENDER_ID: Approved Sender ID (defaults to 'ASDAM')
    - ARKESEL_SMS_URL: API endpoint (defaults to https://sms.arkesel.com/api/v2/sms/send)
    """
    from .models import SMSLog

    recipient = normalize_arkesel_phone(phone)
    formatted_phone = f"+{recipient}" if recipient else str(phone or "").strip()

    # Pre-create SMSLog record
    sms_log = None
    try:
        sms_log = SMSLog.objects.create(
            recipient_phone=formatted_phone,
            recipient_name=recipient_name or getattr(user, "full_name", "") or "",
            user=user if getattr(user, "is_authenticated", True) and hasattr(user, "pk") else None,
            message_body=message,
            sender_id=sender_id or "ASDAM",
            purpose=purpose or "general",
            provider="Arkesel",
            status=SMSLog.DeliveryStatus.PENDING,
        )
    except Exception as exc:
        logger.warning("Could not pre-persist SMSLog record: %s", exc)

    if not recipient:
        detail = "Invalid or empty phone number provided."
        logger.warning("Arkesel SMS skipped: Empty or invalid phone number '%s'.", phone)
        if sms_log:
            try:
                sms_log.status = SMSLog.DeliveryStatus.FAILED
                sms_log.error_detail = detail
                sms_log.save(update_fields=["status", "error_detail", "updated_at"])
            except Exception:
                pass
        return {
            "success": False,
            "phone": phone,
            "detail": detail,
            "sms_log_id": str(sms_log.id) if sms_log else None
        }

    from pathlib import Path
    from dotenv import load_dotenv
    try:
        from django.conf import settings
    except Exception:
        settings = None

    # Check if simulation is explicitly forced or testing
    is_simulation = (
        os.environ.get("SMS_SIMULATION_MODE") == "1"
        or os.environ.get("ARKESEL_SIMULATION_MODE") == "1"
    )

    if not is_simulation and "ARKESEL_API_KEY" not in os.environ:
        env_file = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)

    sender = (
        sender_id
        or os.environ.get("ARKESEL_SENDER_ID")
        or (getattr(settings, "ARKESEL_SENDER_ID", None) if settings else None)
        or os.environ.get("SMS_SENDER_ID")
        or "ASDAM"
    )
    api_key = None if is_simulation else (
        os.environ.get("ARKESEL_API_KEY")
        or (getattr(settings, "ARKESEL_API_KEY", None) if settings else None)
        or os.environ.get("SMS_API_KEY")
    )
    gateway_url = (
        os.environ.get("ARKESEL_SMS_URL")
        or (getattr(settings, "ARKESEL_SMS_URL", None) if settings else None)
        or os.environ.get("SMS_GATEWAY_URL")
        or ARKESEL_V2_URL
    )

    if sms_log:
        try:
            sms_log.sender_id = sender
            sms_log.save(update_fields=["sender_id"])
        except Exception:
            pass

    # If Arkesel API key is configured, perform live API dispatch
    if api_key:
        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "sender": sender,
            "message": message,
            "recipients": [recipient],
        }

        import time
        last_exc = None
        for attempt in range(2):
            try:
                response = requests.post(gateway_url, json=payload, headers=headers, timeout=20)
                try:
                    res_json = response.json()
                except Exception:
                    res_json = {"raw": response.text}

                # Arkesel returns HTTP 200/201 with {"status": "success", ...} on success
                if response.status_code in (200, 201) and (
                    isinstance(res_json, dict) and res_json.get("status") == "success"
                    or "success" in response.text.lower()
                ):
                    msg_id = ""
                    delivery_status = "QUEUED"
                    if isinstance(res_json, dict) and res_json.get("data"):
                        first_item = res_json["data"][0] if (isinstance(res_json["data"], list) and res_json["data"]) else res_json["data"]
                        if isinstance(first_item, dict):
                            msg_id = str(first_item.get("id") or first_item.get("ID") or "")
                            if first_item.get("status"):
                                delivery_status = str(first_item["status"])

                    # Check actual delivery status if message ID returned
                    if msg_id:
                        try:
                            status_resp = requests.get(
                                f"https://sms.arkesel.com/api/v2/sms/{msg_id}",
                                headers={"api-key": api_key},
                                timeout=4
                            )
                            if status_resp.status_code == 200:
                                status_data = status_resp.json().get("data", {})
                                if isinstance(status_data, list) and status_data:
                                    status_data = status_data[0]
                                if isinstance(status_data, dict) and status_data.get("status"):
                                    delivery_status = str(status_data["status"])
                        except Exception:
                            pass

                    # Map Arkesel delivery status to our choices
                    db_status = SMSLog.DeliveryStatus.SUBMITTED
                    delivered_at = None
                    upper_status = delivery_status.upper()
                    if upper_status in ("DELIVERED", "SUCCESSFUL"):
                        db_status = SMSLog.DeliveryStatus.DELIVERED
                        delivered_at = timezone.now()
                    elif upper_status in ("PENDING APPROVAL", "PENDING_APPROVAL"):
                        db_status = SMSLog.DeliveryStatus.PENDING_APPROVAL
                    elif upper_status in ("FAILED", "REJECTED", "UNDELIVERED"):
                        db_status = SMSLog.DeliveryStatus.FAILED

                    if delivery_status == "PENDING APPROVAL":
                        logger.warning(
                            "⚠️ [Arkesel Notice] SMS accepted by Arkesel (ID: %s), but status is 'PENDING APPROVAL'. "
                            "Sender ID '%s' is awaiting approval in your Arkesel dashboard. "
                            "Once approved by Arkesel / NCA, message will be delivered to %s.",
                            msg_id, sender, recipient
                        )
                        detail = (
                            f"SMS queued with Arkesel (ID: {msg_id}), but status is 'PENDING APPROVAL'. "
                            f"The Sender ID '{sender}' must be approved in your Arkesel Dashboard."
                        )
                    else:
                        logger.info(
                            "✅ [Arkesel SMS Sent] To: %s | Sender: %s | Status: %s | ID: %s",
                            recipient, sender, delivery_status, msg_id
                        )
                        detail = f"SMS dispatched successfully via Arkesel (Status: {delivery_status})."

                    if sms_log:
                        try:
                            sms_log.status = db_status
                            sms_log.provider_message_id = msg_id
                            sms_log.status_code = response.status_code
                            sms_log.gateway_response = res_json if isinstance(res_json, dict) else {"raw": str(res_json)}
                            sms_log.sent_at = timezone.now()
                            sms_log.delivered_at = delivered_at
                            sms_log.save(update_fields=[
                                "status", "provider_message_id", "status_code",
                                "gateway_response", "sent_at", "delivered_at", "updated_at"
                            ])
                        except Exception as e:
                            logger.warning("Failed to update SMSLog on success: %s", e)

                    return {
                        "success": True,
                        "phone": f"+{recipient}",
                        "provider": "Arkesel",
                        "sender": sender,
                        "delivery_status": delivery_status,
                        "message_id": msg_id,
                        "sms_log_id": str(sms_log.id) if sms_log else None,
                        "response": res_json,
                        "detail": detail
                    }
                else:
                    logger.warning(
                        "⚠️ [Arkesel SMS Warning] HTTP %s: %s",
                        response.status_code, res_json
                    )
                    detail = f"Arkesel API error: {res_json.get('message') or res_json.get('detail') or response.text}"
                    if sms_log:
                        try:
                            sms_log.status = SMSLog.DeliveryStatus.FAILED
                            sms_log.status_code = response.status_code
                            sms_log.gateway_response = res_json if isinstance(res_json, dict) else {"raw": str(res_json)}
                            sms_log.error_detail = detail
                            sms_log.save(update_fields=["status", "status_code", "gateway_response", "error_detail", "updated_at"])
                        except Exception as e:
                            logger.warning("Failed to update SMSLog on warning: %s", e)

                    return {
                        "success": False,
                        "phone": f"+{recipient}",
                        "provider": "Arkesel",
                        "status_code": response.status_code,
                        "sms_log_id": str(sms_log.id) if sms_log else None,
                        "response": res_json,
                        "detail": detail
                    }
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                logger.warning("Arkesel attempt %d failed for %s: %s", attempt + 1, recipient, exc)
                time.sleep(1)

        err_detail = f"Connection to Arkesel failed: {str(last_exc)}"
        logger.error("❌ [Arkesel SMS Connection Error] To: %s | Err: %s", recipient, last_exc)
        if sms_log:
            try:
                sms_log.status = SMSLog.DeliveryStatus.FAILED
                sms_log.error_detail = err_detail
                sms_log.save(update_fields=["status", "error_detail", "updated_at"])
            except Exception:
                pass

        return {
            "success": False,
            "phone": f"+{recipient}",
            "provider": "Arkesel",
            "sms_log_id": str(sms_log.id) if sms_log else None,
            "detail": err_detail
        }

    # If ARKESEL_API_KEY is not yet populated, record clean simulation
    sim_id = f"SIM-{uuid.uuid4().hex[:12].upper()}"
    logger.info(
        "📱 [ARKESEL SMS SIMULATION]\n"
        "   Recipient:  +%s\n"
        "   Sender ID:  %s\n"
        "   Gateway:    %s\n"
        "   Message:    %s\n"
        "   Note:       Add ARKESEL_API_KEY in backend/.env for live transmission.",
        recipient,
        sender,
        gateway_url,
        message
    )

    if sms_log:
        try:
            sms_log.status = SMSLog.DeliveryStatus.SIMULATED
            sms_log.provider = "Arkesel (Simulated)"
            sms_log.provider_message_id = sim_id
            sms_log.sent_at = timezone.now()
            sms_log.delivered_at = timezone.now()
            sms_log.gateway_response = {"simulation": True, "sender": sender, "recipient": recipient}
            sms_log.save(update_fields=[
                "status", "provider", "provider_message_id", "sent_at",
                "delivered_at", "gateway_response", "updated_at"
            ])
        except Exception as e:
            logger.warning("Failed to update SMSLog on simulation: %s", e)

    return {
        "success": True,
        "phone": f"+{recipient}",
        "provider": "Arkesel (Simulated)",
        "simulated": True,
        "sender": sender,
        "message_id": sim_id,
        "sms_log_id": str(sms_log.id) if sms_log else None,
        "detail": "SMS logged to institutional console. Set ARKESEL_API_KEY in backend/.env for live dispatch."
    }


def check_sms_status(sms_log_or_id: Union[str, Any]) -> Dict[str, Any]:
    """
    Queries Arkesel v2 API to check the current delivery status for an SMSLog record.
    Updates the record in the database with the refreshed carrier delivery status.
    """
    from .models import SMSLog

    if isinstance(sms_log_or_id, SMSLog):
        sms_log = sms_log_or_id
    else:
        try:
            sms_log = SMSLog.objects.get(id=sms_log_or_id)
        except (SMSLog.DoesNotExist, ValueError):
            return {"success": False, "detail": "SMS log record not found."}

    # If it was a simulation, status is already finalized
    if sms_log.status == SMSLog.DeliveryStatus.SIMULATED:
        return {
            "success": True,
            "status": sms_log.status,
            "delivery_status": "DELIVERED (SIMULATED)",
            "detail": "Simulated local dispatch."
        }

    msg_id = sms_log.provider_message_id
    if not msg_id:
        return {
            "success": False,
            "status": sms_log.status,
            "detail": "No provider message ID recorded for this SMS."
        }

    api_key = os.environ.get("ARKESEL_API_KEY")
    if not api_key:
        return {
            "success": False,
            "status": sms_log.status,
            "detail": "ARKESEL_API_KEY not configured."
        }

    try:
        response = requests.get(
            f"https://sms.arkesel.com/api/v2/sms/{msg_id}",
            headers={"api-key": api_key},
            timeout=10
        )
        if response.status_code == 200:
            res_data = response.json()
            status_info = res_data.get("data", {})
            remote_status = str(status_info.get("status") or "QUEUED").upper()

            if remote_status in ("DELIVERED", "SUCCESSFUL"):
                sms_log.status = SMSLog.DeliveryStatus.DELIVERED
                if not sms_log.delivered_at:
                    sms_log.delivered_at = timezone.now()
            elif remote_status in ("PENDING APPROVAL", "PENDING_APPROVAL"):
                sms_log.status = SMSLog.DeliveryStatus.PENDING_APPROVAL
            elif remote_status in ("FAILED", "REJECTED", "UNDELIVERED"):
                sms_log.status = SMSLog.DeliveryStatus.FAILED
            elif remote_status in ("SUBMITTED", "QUEUED"):
                sms_log.status = SMSLog.DeliveryStatus.SUBMITTED

            sms_log.gateway_response = {**(sms_log.gateway_response or {}), "status_check": res_data}
            sms_log.save(update_fields=["status", "delivered_at", "gateway_response", "updated_at"])

            return {
                "success": True,
                "status": sms_log.status,
                "delivery_status": remote_status,
                "data": status_info,
                "detail": f"Status refreshed: {remote_status}"
            }
        else:
            return {
                "success": False,
                "status": sms_log.status,
                "detail": f"Arkesel responded with HTTP {response.status_code}."
            }
    except Exception as exc:
        return {
            "success": False,
            "status": sms_log.status,
            "detail": f"Could not connect to Arkesel: {str(exc)}"
        }


def resend_sms(sms_log_or_id: Union[str, Any]) -> Dict[str, Any]:
    """
    Retries sending an SMS that previously failed or needs redelivery.
    """
    from .models import SMSLog

    if isinstance(sms_log_or_id, SMSLog):
        sms_log = sms_log_or_id
    else:
        try:
            sms_log = SMSLog.objects.get(id=sms_log_or_id)
        except (SMSLog.DoesNotExist, ValueError):
            return {"success": False, "detail": "SMS log record not found."}

    sms_log.retries_count += 1
    sms_log.save(update_fields=["retries_count", "updated_at"])

    return send_sms(
        phone=sms_log.recipient_phone,
        message=sms_log.message_body,
        sender_id=sms_log.sender_id,
        recipient_name=sms_log.recipient_name,
        user=sms_log.user,
        purpose=sms_log.purpose,
    )
