"""Onboarding views — HTMX-based multi-step flow.

See docs/09-ui-screens.md.
Route: GET/POST /app/onboarding/<step>/
"""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.models import Shop
from apps.core.onboarding import (
    ONBOARDING_STEPS,
    advance,
    get_current_step,
    get_next_step,
    get_prev_step,
    get_step_data,
    is_complete,
)

logger = logging.getLogger(__name__)


def onboarding(request: HttpRequest, step: str | None = None) -> HttpResponse:
    """Handle onboarding steps.

    GET: render the step.
    POST: process the step data and advance.
    """
    shop = _get_shop(request)
    if shop is None:
        return HttpResponse("Unauthorized", status=401)

    if is_complete(shop):
        return _redirect_to_dashboard()

    # Determine which step to show
    if step is None:
        step = get_current_step(shop)

    if step not in ONBOARDING_STEPS:
        return HttpResponse("Invalid step", status=400)

    if request.method == "POST":
        return _handle_step_post(request, shop, step)

    # GET: render the step
    context = get_step_data(shop, step)
    context.update(
        {
            "shop": shop,
            "current_step": step,
            "steps": ONBOARDING_STEPS,
            "next_step": get_next_step(step),
            "prev_step": get_prev_step(step),
            "is_first": get_prev_step(step) is None,
        }
    )

    return render(request, f"core/onboarding/{step}.html", context)


def _handle_step_post(request: HttpRequest, shop: Shop, step: str) -> HttpResponse:
    """Process POST data for a step and advance."""
    if step == "language":
        locale = request.POST.get("locale", "en")
        if locale in ("nl", "en", "de"):
            shop.ui_locale = locale
            shop.save(update_fields=["ui_locale"])

    elif step == "brand":
        _handle_brand_step(request, shop)

    elif step == "sources":
        apps = request.POST.getlist("import_apps")
        shop.import_apps = apps
        shop.save(update_fields=["import_apps"])

    elif step == "theme":
        # Deep links are informational — just advance
        pass

    elif step == "withdrawal":
        # Stub until T-085 — just advance
        pass

    # Advance to next step
    next_step = advance(shop)

    if next_step is None:
        # Done
        return _redirect_to_dashboard()

    # HTMX: return the next step's content
    if request.headers.get("HX-Request"):
        context = get_step_data(shop, next_step)
        context.update(
            {
                "shop": shop,
                "current_step": next_step,
                "steps": ONBOARDING_STEPS,
                "next_step": get_next_step(next_step),
                "prev_step": get_prev_step(next_step),
                "is_first": get_prev_step(next_step) is None,
            }
        )
        return render(request, f"core/onboarding/{next_step}.html", context)

    # Regular POST: redirect to next step
    return _redirect_to_onboarding(next_step)


def _handle_brand_step(request: HttpRequest, shop: Shop) -> None:
    """Process the brand step — create/update BrandKit."""
    from apps.themes.models import BrandKit
    from apps.themes.validation import validate_palette

    brand_name = request.POST.get("brand_name", "").strip()
    tone = request.POST.get("tone", "warm")
    style_preset = request.POST.get("style_preset", "clean")
    font_heading = request.POST.get("font_heading", "")
    font_body = request.POST.get("font_body", "")

    # Build palette from form
    palette = {
        "primary": request.POST.get("primary", "#1A1A2E"),
        "secondary": request.POST.get("secondary", "#16213E"),
        "accent": request.POST.get("accent", "#E94560"),
        "background": request.POST.get("background", "#FFFFFF"),
        "text": request.POST.get("text", "#1A1A1A"),
    }

    # Validate palette
    validation = validate_palette(palette)
    if not validation["valid"]:
        logger.warning("Invalid palette for %s: %s", shop.domain, validation["errors"])
        # Still save — the form will show errors
        # For now, use the suggested correction if available
        if "text" in validation["suggestions"]:
            palette["text"] = validation["suggestions"]["text"]

    if brand_name:
        BrandKit.objects.update_or_create(
            shop=shop,
            defaults={
                "brand_name": brand_name,
                "tone": tone,
                "palette": palette,
                "style_preset": style_preset,
                "font_heading": font_heading,
                "font_body": font_body,
            },
        )


def _get_shop(request: HttpRequest) -> Shop | None:
    """Get the shop from the request (via session token middleware)."""
    # This would be populated by SessionTokenMiddleware
    shop_id = getattr(request, "shop_id", None)
    if shop_id:
        try:
            return Shop.objects.get(id=shop_id)
        except Shop.DoesNotExist:
            return None
    return None


def _redirect_to_dashboard() -> HttpResponse:
    """Redirect to the dashboard."""
    from django.http import HttpResponseRedirect

    return HttpResponseRedirect("/app/dashboard/")


def _redirect_to_onboarding(step: str) -> HttpResponse:
    """Redirect to an onboarding step."""
    from django.http import HttpResponseRedirect

    return HttpResponseRedirect(f"/app/onboarding/{step}/")
