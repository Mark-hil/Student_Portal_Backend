"""IP-based rate limiting via Redis."""
from django.core.cache import cache
from django.http import JsonResponse

EXEMPT = ["/health/", "/admin/"]


class RateLimitMiddleware:
    LIMIT  = 300  # requests
    WINDOW = 60   # seconds

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in EXEMPT):
            return self.get_response(request)

        ip    = self._ip(request)
        key   = f"rl:{ip}"
        count = cache.get(key, 0)
        cache.set(key, count + 1, self.WINDOW)

        if count >= self.LIMIT:
            return JsonResponse(
                {"error": "rate_limit_exceeded", "detail": "Too many requests."},
                status=429,
                headers={"Retry-After": str(self.WINDOW)},
            )
        return self.get_response(request)

    def _ip(self, request):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR")
        return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "unknown")
