"""Compliance views — delivery profiles and product override screens (F18-1..2)."""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render

logger = logging.getLogger(__name__)


def _get_shop(request: HttpRequest):
    from apps.core.models import Shop

    shop_domain = getattr(request, "shop_domain", None)
    return Shop.objects.filter(domain=shop_domain).first() if shop_domain else None


def _parse_json_field(raw: str, field: str, errors: list[str]):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        errors.append(f"{field}: invalid JSON.")
        return None
    return value


def _set_profile_fields(profile, post) -> list[str]:
    """Apply POST data to a DeliveryProfile; return validation errors."""
    errors: list[str] = []

    profile.ship_from_country = post.get("ship_from_country", "").strip().upper()
    try:
        profile.processing_days_min = int(post.get("processing_days_min") or 0)
        profile.processing_days_max = int(post.get("processing_days_max") or 0)
    except ValueError:
        errors.append("Processing days must be numbers.")
        return errors

    transit = _parse_json_field(post.get("transit_days", ""), "Transit days", errors)
    if transit is not None and not isinstance(transit, dict):
        errors.append("Transit days must be a JSON object per market.")
        transit = None
    profile.transit_days = transit if transit is not None else {}

    cost = _parse_json_field(post.get("shipping_cost", ""), "Shipping cost", errors)
    if cost is not None and not isinstance(cost, dict):
        errors.append("Shipping cost must be a JSON object per market.")
        cost = None
    profile.shipping_cost = cost

    if errors:
        return errors
    try:
        profile.full_clean()
    except Exception as exc:  # django.core.exceptions.ValidationError
        if hasattr(exc, "message_dict"):
            for field_errors in exc.message_dict.values():
                errors.extend(field_errors)
        else:
            errors.append(str(exc))
    return errors


def delivery_profiles(request: HttpRequest) -> HttpResponse:
    """Delivery profiles per source app (F18-1, docs/12 §6).

    GET/POST /app/settings/delivery/ — one row per source app the shop uses
    (Shop.import_apps + detected sources) plus `manual`. Saving also writes
    the app-data `settings`-level sync via compliance.tasks.
    """
    from apps.compliance.models import DeliveryProfile
    from apps.compliance.tasks import sync_delivery_metafields
    from apps.sources.models import ProductSource

    shop = _get_shop(request)
    if shop is None:
        return JsonResponse({"error": "Shop not found"}, status=404)

    # Rows cover import_apps + detected sources + manual
    detected = set(
        ProductSource.objects.filter(shop=shop).values_list("source", flat=True)
    )
    source_apps: list[str] = []
    for app in (shop.import_apps or []) + sorted(detected) + ["manual"]:
        if app and app not in source_apps:
            source_apps.append(app)

    profiles = {p.source_app: p for p in DeliveryProfile.objects.filter(shop=shop)}

    if request.method == "POST":
        source_app = request.POST.get("source_app", "").strip()
        if source_app not in source_apps:
            messages.error(request, "Unknown source app.")
        else:
            profile = profiles.get(source_app) or DeliveryProfile(
                shop=shop, source_app=source_app
            )
            errors = _set_profile_fields(profile, request.POST)
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                profile.save()
                from apps.core.models import AuditLog

                AuditLog.objects.create(
                    shop=shop,
                    actor="merchant",
                    action="delivery_profile_saved",
                    payload={"source_app": source_app},
                )
                sync_delivery_metafields.delay(shop.domain)
                messages.success(request, "Delivery profile saved.")
                return redirect("/app/settings/delivery/")

    return render(
        request,
        "app/delivery_profiles.html",
        {
            "shopify_api_key": settings.SHOPIFY_API_KEY,
            "shop_domain": shop.domain,
            "ui_locale": getattr(request, "ui_locale", "en"),
            "shop": shop,
            "rows": [
                {
                    "app": app,
                    "ship_from_country": profiles[app].ship_from_country if app in profiles else "",
                    "processing_days_min": profiles[app].processing_days_min if app in profiles else "",
                    "processing_days_max": profiles[app].processing_days_max if app in profiles else "",
                    "transit_days": (
                        json.dumps(profiles[app].transit_days)
                        if app in profiles and profiles[app].transit_days
                        else ""
                    ),
                    "shipping_cost": (
                        json.dumps(profiles[app].shipping_cost)
                        if app in profiles and profiles[app].shipping_cost
                        else ""
                    ),
                }
                for app in source_apps
            ],
        },
    )


def delivery_override(request: HttpRequest, product_gid: str) -> HttpResponse:
    """Per-product delivery override (F18-2, docs/12 §6).

    GET/POST /app/products/<gid>/delivery/ — empty fields fall back to the
    profile; posting an entirely empty form deletes the override.
    """
    from apps.compliance.models import DeliveryOverride
    from apps.compliance.tasks import sync_delivery_metafields

    shop = _get_shop(request)
    if shop is None:
        return JsonResponse({"error": "Shop not found"}, status=404)

    override = DeliveryOverride.objects.filter(
        shop=shop, product_gid=product_gid
    ).first()

    if request.method == "POST":
        has_any = any(
            (request.POST.get(name) or "").strip()
            for name in (
                "ship_from_country",
                "processing_days_min",
                "processing_days_max",
                "transit_days",
                "shipping_cost",
            )
        )
        if not has_any:
            if override:
                override.delete()
                sync_delivery_metafields.delay(shop.domain)
                messages.success(request, "Delivery override removed.")
            return redirect(f"/app/products/{quote(product_gid, safe='')}/delivery/")

        row = override or DeliveryOverride(shop=shop, product_gid=product_gid)
        errors: list[str] = []

        row.ship_from_country = (
            request.POST.get("ship_from_country", "").strip().upper() or None
        )
        for name in ("processing_days_min", "processing_days_max"):
            raw = (request.POST.get(name) or "").strip()
            try:
                setattr(row, name, int(raw) if raw else None)
            except ValueError:
                errors.append("Processing days must be numbers.")

        transit = _parse_json_field(request.POST.get("transit_days", ""), "Transit days", errors)
        if transit is not None and not isinstance(transit, dict):
            errors.append("Transit days must be a JSON object per market.")
            transit = None
        row.transit_days = transit

        cost = _parse_json_field(request.POST.get("shipping_cost", ""), "Shipping cost", errors)
        if cost is not None and not isinstance(cost, dict):
            errors.append("Shipping cost must be a JSON object per market.")
            cost = None
        row.shipping_cost = cost

        if not errors:
            try:
                row.full_clean()
            except Exception as exc:  # ValidationError
                if hasattr(exc, "message_dict"):
                    for field_errors in exc.message_dict.values():
                        errors.extend(field_errors)
                else:
                    errors.append(str(exc))

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            row.save()
            from apps.core.models import AuditLog

            AuditLog.objects.create(
                shop=shop,
                actor="merchant",
                action="delivery_override_saved",
                payload={"product_gid": product_gid},
            )
            sync_delivery_metafields.delay(shop.domain)
            messages.success(request, "Delivery override saved.")
            return redirect(f"/app/products/{quote(product_gid, safe='')}/delivery/")

    return render(
        request,
        "app/delivery_override.html",
        {
            "shopify_api_key": settings.SHOPIFY_API_KEY,
            "shop_domain": shop.domain,
            "ui_locale": getattr(request, "ui_locale", "en"),
            "shop": shop,
            "product_gid": product_gid,
            "override": override,
        },
    )


def price_advisor(request: HttpRequest, product_gid: str) -> HttpResponse:
    """Price advisor screen (F17-1..3, 6..7, docs/12 §6).

    GET/POST /app/products/<gid>/pricing/ — computes a price advice per
    market from PricingSettings defaults. Advisory only for non-base markets.
    """
    from apps.compliance.models import PricingSettings
    from apps.compliance.pricing_advisor import advise
    from apps.compliance.vat_rates import GB_NOT_COVERED_MESSAGE, vat_rate_for

    shop = _get_shop(request)
    if shop is None:
        return JsonResponse({"error": "Shop not found"}, status=404)

    from apps.sources.models import ProductSource

    ps, _ = PricingSettings.objects.get_or_create(shop=shop)
    advice = None
    market = ""
    cost = shipping = ad_cost = ""
    margin_pct = returns_pct = ""

    # Ownership (F17-5): only Mosaiq-created products may have price applied
    src = ProductSource.objects.filter(shop=shop, product_gid=product_gid).first()
    writable = bool(src and src.created_by_mosaiq)
    app_label = src.get_source_display() if src else None

    # Current price (F17-3 remainder) — best effort, never blocks the screen
    current_price = None
    try:
        from apps.compliance.tasks import _get_client
        from apps.core.shopify_client import load_query

        client = _get_client(shop)
        pdata = client.execute(load_query("product_variants_by_product"), {"id": product_gid})
        nodes = pdata.get("product", {}).get("variants", {}).get("nodes", [])
        if nodes and nodes[0].get("price") is not None:
            current_price = Decimal(nodes[0]["price"])
    except Exception:
        current_price = None

    advice_id = None
    omnibus_warning = False
    price_diff = None

    if request.method == "POST":
        market = request.POST.get("market", "NL").strip().upper()
        cost = request.POST.get("cost", "").strip()
        shipping = request.POST.get("shipping", "").strip()
        ad_cost = request.POST.get("ad_cost", "0").strip() or "0"
        margin_pct = request.POST.get("margin_pct", "").strip()
        returns_pct = request.POST.get("returns_pct", "").strip()

        vat = vat_rate_for(market)
        if vat is None:
            advice = {"error": GB_NOT_COVERED_MESSAGE}
        else:
            try:
                m_pct = Decimal(margin_pct) / 100 if margin_pct else ps.target_margin_pct
                r_pct = Decimal(returns_pct) / 100 if returns_pct else ps.returns_allowance_pct
                result = advise(
                    cost=Decimal(cost or "0"),
                    shipping=Decimal(shipping or "0"),
                    ad_cost=Decimal(ad_cost or "0"),
                    payment_fee_fixed=ps.payment_fee_fixed,
                    payment_fee_pct=ps.payment_fee_pct,
                    returns_pct=r_pct,
                    margin_pct=m_pct,
                    vat_rate=vat,
                    price_ending=int(ps.price_ending),
                )
                advice = {"result": result, "market": market, "vat": vat}
                if result.error is None:
                    from apps.compliance.models import PriceAdvice

                    row = PriceAdvice.objects.create(
                        shop=shop,
                        product_gid=product_gid,
                        market=market,
                        inputs={
                            "cost": cost,
                            "shipping": shipping,
                            "ad_cost": ad_cost,
                            "margin_pct": margin_pct,
                            "returns_pct": returns_pct,
                        },
                        advice={
                            "break_even": str(result.break_even_price),
                            "consumer": str(result.consumer_price),
                            "rounded": str(result.rounded_price),
                            "actual_margin": str(
                                (result.actual_margin * 100).quantize(Decimal("0.1"))
                            )
                            if result.actual_margin is not None
                            else None,
                        },
                    )
                    advice_id = str(row.id)
                    if current_price is not None and result.rounded_price is not None:
                        price_diff = result.rounded_price - current_price
                        omnibus_warning = price_diff > 0
            except (InvalidOperation, ValueError):
                advice = {"error": "Invalid number in cost fields."}

    return render(
        request,
        "app/price_advisor.html",
        {
            "shopify_api_key": settings.SHOPIFY_API_KEY,
            "shop_domain": shop.domain,
            "ui_locale": getattr(request, "ui_locale", "en"),
            "shop": shop,
            "product_gid": product_gid,
            "ps": ps,
            "advice": advice,
            "market": market,
            "cost": cost,
            "shipping": shipping,
            "ad_cost": ad_cost,
            "margin_pct": margin_pct,
            "returns_pct": returns_pct,
            "writable": writable,
            "app_label": app_label,
            "current_price": current_price,
            "advice_id": advice_id,
            "omnibus_warning": omnibus_warning,
            "price_diff": price_diff,
        },
    )


def price_apply(request: HttpRequest, product_gid: str) -> HttpResponse:
    """Apply an advice price to a writable product (F17-4).

    POST /app/products/<gid>/pricing/apply/ — asserts writability, writes the
    rounded price with productVariantsBulkUpdate (price only), stores
    PriceAdvice.applied_at, and logs to AuditLog. Sync-app products are refused
    before any HTTP call (F17-5).
    """
    from django.shortcuts import redirect
    from django.utils import timezone

    from apps.compliance.models import PriceAdvice
    from apps.core.models import AuditLog
    from apps.sources.guards import LockedFieldError, assert_writable

    shop = _get_shop(request)
    if shop is None:
        return JsonResponse({"error": "Shop not found"}, status=404)

    qs = request.GET.urlencode()
    back = f"/app/products/{product_gid}/pricing/"
    if qs:
        back = f"{back}?{qs}"

    if request.method != "POST":
        return redirect(back)

    advice_id = request.POST.get("advice_id", "")
    try:
        advice_row = PriceAdvice.objects.get(id=advice_id, shop=shop)
    except Exception:
        messages.error(request, "Price advice not found.")
        return redirect(back)

    from apps.sources.models import ProductSource

    src = ProductSource.objects.filter(shop=shop, product_gid=product_gid).first()
    if not (src and src.created_by_mosaiq):
        label = src.get_source_display() if src else None
        if label:
            messages.error(request, f"Set this price in {label} (price rules).")
        else:
            messages.error(
                request,
                "This product is managed by a sync app — set the price there.",
            )
        return redirect(back)

    try:
        assert_writable(shop, product_gid, {"price"})
    except LockedFieldError as exc:
        messages.error(request, str(exc))
        return redirect(back)

    price_str = str(advice_row.advice.get("rounded", ""))
    if not price_str:
        messages.error(request, "No rounded price in this advice.")
        return redirect(back)

    try:
        from apps.compliance.tasks import _get_client
        from apps.core.shopify_client import load_query

        client = _get_client(shop)
        pdata = client.execute(load_query("product_variants_by_product"), {"id": product_gid})
        nodes = pdata.get("product", {}).get("variants", {}).get("nodes", [])
        if not nodes:
            messages.error(request, "No variants found for this product.")
            return redirect(back)
        client.execute(
            load_query("product_variants_bulk_update"),
            {
                "productId": product_gid,
                "variants": [
                    {"id": n["id"], "price": price_str}
                    for n in nodes
                    if n.get("id")
                ],
            },
        )
    except Exception as exc:
        messages.error(request, f"Could not apply price: {exc}")
        return redirect(back)

    advice_row.applied_at = timezone.now()
    advice_row.applied_price = Decimal(price_str)
    advice_row.save(update_fields=["applied_at", "applied_price"])

    AuditLog.objects.create(
        shop=shop,
        actor="merchant",
        action="price_advisor_applied",
        payload={
            "product_gid": product_gid,
            "market": advice_row.market,
            "price": price_str,
            "advice_id": str(advice_row.id),
            "variant_count": len(nodes),
        },
    )
    messages.success(request, f"Price {price_str} applied to {len(nodes)} variant(s).")
    return redirect(back)


def _get_client(shop):
    """ShopifyGraphQLClient for a shop (T-161: GPSR form + metafield sync)."""
    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient

    return ShopifyGraphQLClient(
        shop.domain,
        decrypt_token(shop.access_token_encrypted),
        settings.SHOPIFY_API_VERSION,
    )


GPSR_FIELDS = (
    "manufacturer_name",
    "manufacturer_address",
    "manufacturer_email",
    "eu_rp_name",
    "eu_rp_address",
    "eu_rp_email",
    "product_identifier",
    "warnings",
)


def gpsr_form(request: HttpRequest, product_gid: str) -> HttpResponse:
    """Per-product GPSR form (T-161, F11-E, 07 §5).

    GET/POST /app/products/<gid>/gpsr/ — value stored in the product
    metafield `$app:mosaiq.gpsr` (same field the mq-gpsr block renders).
    Incomplete GPSR can be saved; publish stays blocked until complete.
    """

    from apps.compliance.gpsr import GpsrInfo
    from apps.compliance.gpsr_loader import load_gpsr_info, sync_gpsr_metafield
    from apps.core.models import AuditLog

    shop = _get_shop(request)
    if shop is None:
        return JsonResponse({"error": "Shop not found"}, status=404)

    if request.method == "POST":
        info = GpsrInfo(
            manufacturer_name=(request.POST.get("manufacturer_name") or "").strip(),
            manufacturer_address=(request.POST.get("manufacturer_address") or "").strip(),
            manufacturer_email=(request.POST.get("manufacturer_email") or "").strip(),
            manufacturer_in_eu=request.POST.get("manufacturer_in_eu") == "on",
            eu_rp_name=(request.POST.get("eu_rp_name") or "").strip(),
            eu_rp_address=(request.POST.get("eu_rp_address") or "").strip(),
            eu_rp_email=(request.POST.get("eu_rp_email") or "").strip(),
            product_identifier=(request.POST.get("product_identifier") or "").strip(),
            warnings=(request.POST.get("warnings") or "").strip(),
            no_warnings_confirmed=request.POST.get("no_warnings_confirmed") == "on",
            content_locale=shop.ui_locale if hasattr(shop, "ui_locale") else "nl",
        )
        errors = sync_gpsr_metafield(shop, product_gid, info, client=_get_client(shop))
        if errors:
            messages.error(request, errors[0].get("message", "Could not save GPSR data."))
        else:
            AuditLog.objects.create(
                shop=shop,
                actor="merchant",
                action="gpsr_saved",
                payload={"product_gid": product_gid, "complete": info.complete},
            )
            if info.complete:
                messages.success(request, "GPSR data saved. This product can now be published.")
            else:
                missing = ", ".join(info.missing_fields)
                messages.warning(
                    request,
                    f"Saved, but incomplete (missing: {missing}). Publishing stays blocked until complete.",
                )
        return redirect(f"/app/products/{quote(product_gid, safe='')}/gpsr/")

    client = _get_client(shop)
    info = load_gpsr_info(client, product_gid)
    return render(
        request,
        "app/gpsr_form.html",
        {"info": info, "product_gid": product_gid},
    )
