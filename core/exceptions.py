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

    code   = getattr(exc, "default_code", "error")
    detail = response.data

    if isinstance(detail, dict):
        response.data = {"error": code, "detail": str(exc), "errors": detail}
    elif isinstance(detail, list):
        response.data = {"error": code, "detail": detail[0] if detail else "Error", "errors": detail}
    else:
        response.data = {"error": code, "detail": str(detail)}

    return response
