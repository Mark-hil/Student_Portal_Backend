"""Structured request logging."""
import time, uuid, logging

logger = logging.getLogger("apps.requests")


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = str(uuid.uuid4())
        request.META["X_REQUEST_ID"] = request_id
        t0 = time.monotonic()

        response = self.get_response(request)

        ms = round((time.monotonic() - t0) * 1000, 2)
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method":     request.method,
                "path":       request.path,
                "status":     response.status_code,
                "ms":         ms,
                "user":       str(request.user.pk) if request.user.is_authenticated else None,
                "ip":         self._ip(request),
            },
        )
        response["X-Request-ID"] = request_id
        return response

    def _ip(self, request):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR")
        return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")
