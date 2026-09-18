"""
SMS Dispatch Service — Powered by Arkesel (https://arkesel.com).
Implements the official Arkesel SMS API v2 for reliable, high-deliverability SMS across Ghana
and international destinations.
Includes automatic Ghana phone normalization (e.g. 0241234567 -> 233241234567).
Gracefully falls back to console simulation if ARKESEL_API_KEY is not configured.
"""
import os
import re
import json
import logging
import requests
from typing import Optional, Dict, Any, List

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
    sender_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Sends an SMS via the official Arkesel SMS API v2.
    
    Configuration (via environment variables or settings):
    - ARKESEL_API_KEY: Your Arkesel API Key from https://sms.arkesel.com
    - ARKESEL_SENDER_ID: Approved Sender ID (defaults to 'ASDAM' or institutional sender)
    - ARKESEL_SMS_URL: API endpoint (defaults to https://sms.arkesel.com/api/v2/sms/send)
    """
    recipient = normalize_arkesel_phone(phone)
    if not recipient:
        logger.warning("Arkesel SMS skipped: Empty or invalid phone number '%s'.", phone)
        return {"success": False, "phone": phone, "detail": "Invalid phone number provided."}

    from pathlib import Path
    from dotenv import load_dotenv
    try:
        from django.conf import settings
    except Exception:
        settings = None

    # Dynamically refresh .env so changes take effect immediately without requiring server restart
    env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
        if not os.environ.get("ARKESEL_API_KEY"):
            load_dotenv(env_file, override=True)

    sender = (
        sender_id
        or os.environ.get("ARKESEL_SENDER_ID")
        or (getattr(settings, "ARKESEL_SENDER_ID", None) if settings else None)
        or os.environ.get("SMS_SENDER_ID")
        or "ASDAM"
    )
    api_key = (
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

                # Arkesel returns HTTP 200 with {"status": "success", ...} on success
                if response.status_code in (200, 201) and (
                    isinstance(res_json, dict) and res_json.get("status") == "success"
                    or "success" in response.text.lower()
                ):
                    msg_id = None
                    delivery_status = "QUEUED"
                    if isinstance(res_json, dict) and res_json.get("data"):
                        first_item = res_json["data"][0] if isinstance(res_json["data"], list) else res_json["data"]
                        if isinstance(first_item, dict):
                            msg_id = first_item.get("id") or first_item.get("ID")

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
                                delivery_status = status_data.get("status", "QUEUED")
                        except Exception:
                            pass

                    if delivery_status == "PENDING APPROVAL":
                        logger.warning(
                            "⚠️ [Arkesel Notice] SMS accepted by Arkesel (ID: %s), but status is 'PENDING APPROVAL'. "
                            "Sender ID '%s' is awaiting approval in your Arkesel dashboard (https://sms.arkesel.com). "
                            "Once approved by Arkesel / NCA, the message will be delivered to %s.",
                            msg_id, sender, recipient
                        )
                        detail = (
                            f"SMS queued with Arkesel (ID: {msg_id}), but status is 'PENDING APPROVAL'. "
                            f"The Sender ID '{sender}' must be approved in your Arkesel Dashboard before telcos deliver it."
                        )
                    else:
                        logger.info(
                            "✅ [Arkesel SMS Sent] To: %s | Sender: %s | Status: %s | ID: %s",
                            recipient, sender, delivery_status, msg_id
                        )
                        detail = f"SMS dispatched successfully via Arkesel (Status: {delivery_status})."

                    return {
                        "success": True,
                        "phone": f"+{recipient}",
                        "provider": "Arkesel",
                        "sender": sender,
                        "delivery_status": delivery_status,
                        "message_id": msg_id,
                        "response": res_json,
                        "detail": detail
                    }
                else:
                    logger.warning(
                        "⚠️ [Arkesel SMS Warning] HTTP %s: %s",
                        response.status_code, res_json
                    )
                    return {
                        "success": False,
                        "phone": f"+{recipient}",
                        "provider": "Arkesel",
                        "status_code": response.status_code,
                        "response": res_json,
                        "detail": f"Arkesel API error: {res_json.get('message') or res_json.get('detail') or response.text}"
                    }
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                logger.warning("Arkesel attempt %d failed for %s: %s", attempt + 1, recipient, exc)
                time.sleep(1)

        logger.error("❌ [Arkesel SMS Connection Error] To: %s | Err: %s", recipient, last_exc)
        return {
            "success": False,
            "phone": f"+{recipient}",
            "provider": "Arkesel",
            "detail": f"Connection to Arkesel failed: {str(last_exc)}"
        }


    # If ARKESEL_API_KEY is not yet populated, log clean simulation in dev/test
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
    return {
        "success": True,
        "phone": f"+{recipient}",
        "provider": "Arkesel (Simulated)",
        "simulated": True,
        "sender": sender,
        "detail": "SMS logged to institutional console. Set ARKESEL_API_KEY in backend/.env for live dispatch."
    }

