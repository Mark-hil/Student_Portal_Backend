"""Normalised error shape: {error, detail, errors?}"""
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        logger.exception("Unhandled exception in %s", context.get("view"))
        return Response(
            {"error": "internal_server_error", "detail": "An unexpected error occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = getattr(exc, "default_code", "error")
    raw_data = response.data

    if isinstance(raw_data, dict):
        # Extract user-facing string detail instead of Python str(exc) / ErrorDetail repr
        if "detail" in raw_data:
            d = raw_data["detail"]
            user_detail = d[0] if isinstance(d, (list, tuple)) else str(d)
        elif raw_data:
            first_val = next(iter(raw_data.values()))
            user_detail = first_val[0] if isinstance(first_val, (list, tuple)) else str(first_val)
        else:
            user_detail = "Validation error."

        code_val = raw_data.get("code")
        if isinstance(code_val, (list, tuple)) and code_val:
            code_val = str(code_val[0])
        elif code_val:
            code_val = str(code_val)
        else:
            code_val = code

        payload = {
            "error": code_val,
            "detail": str(user_detail),
            "errors": raw_data,
        }
        for key in ("code", "suggest_activation", "suggest_reset"):
            if key in raw_data:
                val = raw_data[key]
                if isinstance(val, (list, tuple)) and val:
                    val = val[0]
                val_str = str(val)
                if val_str.lower() == "true":
                    payload[key] = True
                elif val_str.lower() == "false":
                    payload[key] = False
                else:
                    payload[key] = val_str
        response.data = payload

    elif isinstance(raw_data, list):
        user_detail = raw_data[0] if raw_data else "Error"
        response.data = {
            "error": code,
            "detail": str(user_detail),
            "errors": raw_data,
        }
    else:
        response.data = {"error": code, "detail": str(raw_data)}

    return response
