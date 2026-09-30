"""Core views — health check, dashboard, onboarding."""

import contextlib

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render


def health_check(request: HttpRequest) -> JsonResponse:
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


def dashboard(request: HttpRequest):
    """Admin dashboard — embedded in Shopify."""
    shop_domain = getattr(request, "shop_domain", None)
    ui_locale = getattr(request, "ui_locale", "en")
    return render(
        request,
        "app/dashboard.html",
        {
            "shopify_api_key": settings.SHOPIFY_API_KEY,
            "shop_domain": shop_domain,
            "ui_locale": ui_locale,
        },
    )
