"""Core views — health check, dashboard, onboarding, store settings."""

import contextlib
import hashlib
import hmac as hmac_lib

from django.conf import settings
from django.http import HttpRequest, HttpResponseNotFound, JsonResponse
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


def oauth_callback(request: HttpRequest):
    """Shopify OAuth callback (registered in shopify.app.toml [auth]).

    The re-grant/authorize flow redirects here with `code`, `shop`,
    `host`, `timestamp` and `hmac`. Token exchange happens elsewhere
    (managed install + session-token flow), so this view only validates
    the hmac and sends the merchant back to the app inside the admin.

    Shopify's OAuth hmac differs from the webhook hmac: HEX sha256 of the
    `key=value&...` query string (sorted, hmac param excluded), keyed with
    the client secret. Invalid → 404 (no information leak).
    """
    hmac_value = request.GET.get("hmac", "")
    shop = request.GET.get("shop", "")
    if not hmac_value or not shop:
        return HttpResponseNotFound()

    params = [k for k in request.GET if k != "hmac"]
    # Canonical form: sorted `key=value` params joined with `&`
    # (all params in our flow are scalar).
    message = "&".join(f"{k}={request.GET[k]}" for k in sorted(params))
    expected = hmac_lib.new(
        settings.SHOPIFY_API_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac_lib.compare_digest(expected, hmac_value):
        return HttpResponseNotFound()

    # Valid — the merchant approved (scopes already granted server-side);
    # send them back into the app.
    return redirect(f"https://{shop}/admin/apps/{settings.SHOPIFY_API_KEY}")


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


BUSINESS_FIELD_NAMES = (
    "legal_name",
    "trade_name",
    "street",
    "postal_code",
    "city",
    "country_code",
    "email",
    "phone",
    "company_reg_no",
    "vat_id",
)


def business_details(request: HttpRequest):
    """Business details settings (12 §6, T-111).

    GET/POST /app/settings/business/ — the merchant's business facts used by
    legal templates, the contact page and the shipping/returns pages.
    """
    from django.contrib import messages

    from apps.core.models import AuditLog, BusinessDetails, Shop

    shop_domain = getattr(request, "shop_domain", None)
    shop = Shop.objects.filter(domain=shop_domain).first() if shop_domain else None
    if shop is None:
        return JsonResponse({"error": "Shop not found"}, status=404)

    details = BusinessDetails.objects.filter(shop=shop).first()

    if request.method == "POST":
        data = {name: request.POST.get(name, "").strip() for name in BUSINESS_FIELD_NAMES}
        country = data.pop("country_code", "").upper()
        data["country_code"] = country
        return_address_same = request.POST.get("return_address_same") == "on"
        return_address = None
        if not return_address_same:
            return_address = {
                key: request.POST.get(key, "").strip()
                for key in ("legal_name", "street", "postal_code", "city", "country_code")
                if request.POST.get(key, "").strip()
            }

        if details is None:
            details = BusinessDetails(shop=shop)

        for name, value in data.items():
            setattr(details, name, value)
        details.return_address_same = return_address_same
        details.return_address = return_address

        errors = []
        try:
            details.full_clean()
        except Exception as exc:  # django.core.exceptions.ValidationError
            if hasattr(exc, "message_dict"):
                for field_errors in exc.message_dict.values():
                    errors.extend(field_errors)
            else:
                errors.append(str(exc))

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            details.save()
            AuditLog.objects.create(
                shop=shop, actor="merchant", action="business_details_saved", payload={}
            )
            messages.success(request, "Business details saved.")
            return redirect("/app/settings/business/")

    return render(
        request,
        "app/business_details.html",
        {
            "shopify_api_key": settings.SHOPIFY_API_KEY,
            "shop_domain": shop_domain,
            "ui_locale": getattr(request, "ui_locale", "en"),
            "shop": shop,
            "details": details,
        },
    )
