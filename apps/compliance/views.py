"""Compliance views — delivery profiles and product override screens (F18-1..2)."""

from __future__ import annotations

import json
import logging
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
