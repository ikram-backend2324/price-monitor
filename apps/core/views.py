from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse


def health(request):
    """Liveness/readiness probe used by Docker, Nginx and uptime monitors."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:  # pragma: no cover - only when DB is down
        checks["db"] = f"error: {exc.__class__.__name__}"
    try:
        cache.set("health:ping", "1", 10)
        checks["cache"] = "ok" if cache.get("health:ping") == "1" else "error"
    except Exception as exc:  # pragma: no cover
        checks["cache"] = f"error: {exc.__class__.__name__}"
    healthy = all(v == "ok" for v in checks.values())
    return JsonResponse({"status": "ok" if healthy else "degraded", **checks}, status=200 if healthy else 503)
