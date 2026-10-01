"""Core views — health check, dashboard, onboarding, store settings."""

import contextlib

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect, render


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
    from .auth_flow import ensure_shop

    shop_domain = getattr(request, "shop_domain", None)
    ui_locale = getattr(request, "ui_locale", "en")

    # First load inside the admin iframe: bootstrap the shop via token
    # exchange if needed (docs/03-shopify-integration.md §2.1).
    shop = ensure_shop(request) if shop_domain else None

    return render(
        request,
        "app/dashboard.html",
        {
            "shopify_api_key": settings.SHOPIFY_API_KEY,
            "shop_domain": shop_domain,
            "ui_locale": ui_locale,
            "shop": shop,
        },
    )


def store_settings(request: HttpRequest):
    """Store settings — warranty policy, shipping cutoff, AI label, stock threshold.

    See docs/09-ui-screens.md (GET/POST /app/settings/store/).
    """
    from apps.core.models import Shop
    from apps.core.store_settings import save_settings

    shop_domain = getattr(request, "shop_domain", None)
    shop = Shop.objects.filter(domain=shop_domain).first() if shop_domain else None
    if shop is None:
        return JsonResponse({"error": "Shop not found"}, status=404)

    errors = []
    if request.method == "POST":
        guarantee_policy = request.POST.get("guarantee_policy", "")
        stock_threshold = int(request.POST.get("stock_threshold", 5))
        ai_label_default = request.POST.get("ai_label_default") == "on"

        cutoff_time = request.POST.get("ship_cutoff_time", "")
        cutoff_days = request.POST.getlist("ship_cutoff_days")
        delivery_days = request.POST.get("delivery_days", "")
        ship_cutoff = None
        if cutoff_time or cutoff_days:
            ship_cutoff = {
                "time": cutoff_time,
                "days": cutoff_days,
                "delivery_days": int(delivery_days) if delivery_days else 1,
            }

        errors = save_settings(
            shop,
            guarantee_policy=guarantee_policy,
            ship_cutoff=ship_cutoff,
            ai_label_default=ai_label_default,
            stock_threshold=stock_threshold,
        )

        if not errors:
            from django.contrib import messages

            messages.success(request, "Settings saved and synced to store.")
            return redirect("/app/settings/store/")
        else:
            from django.contrib import messages

            for error in errors:
                messages.error(request, error)

    return render(
        request,
        "app/store_settings.html",
        {
            "shopify_api_key": settings.SHOPIFY_API_KEY,
            "shop_domain": shop_domain,
            "ui_locale": getattr(request, "ui_locale", "en"),
            "shop": shop,
            "errors": errors,
        },
    )
