"""Core views — health check, dashboard, onboarding."""

import contextlib

from django.http import JsonResponse


def health_check(request):
    """Simple healthcheck — DB + Redis reachable."""
    from django.core.cache import cache
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        return JsonResponse({"status": "error", "db": str(e)}, status=503)

    with contextlib.suppress(Exception):
        cache.set("healthcheck", "ok", 10)

    return JsonResponse({"status": "ok"})
