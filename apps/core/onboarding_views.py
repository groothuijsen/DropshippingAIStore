"""Onboarding views — HTMX-based multi-step flow.

See docs/09-ui-screens.md.
Route: GET/POST /app/onboarding/<step>/
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.core.models import Shop

if TYPE_CHECKING:
    from django.http import HttpRequest

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
    if step == "brand" and shop.onboarding_route == "zero":
        extras = _brand_step_extras(shop, request)
        if isinstance(extras, HttpResponse):
            return extras
        context.update(extras)

    context.update(_base_context(request))
    return render(request, f"core/onboarding/{step}.html", context)


def _handle_step_post(request: HttpRequest, shop: Shop, step: str) -> HttpResponse:
    """Process POST data for a step and advance."""
    if step == "language":
        locale = request.POST.get("locale", "en")
        if locale in ("nl", "en", "de"):
            shop.ui_locale = locale
            shop.save(update_fields=["ui_locale"])

    elif step == "brand":
        response = _handle_brand_step(request, shop)
        if response is not None:
            return response

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
        context.update(_base_context(request))
        return render(request, f"core/onboarding/{next_step}.html", context)

    # Regular POST: redirect to next step
    return _redirect_to_onboarding(next_step)


def _handle_brand_step(request: HttpRequest, shop: Shop) -> HttpResponse | None:
    """Process the brand step — route choice (F15-1) + create/update BrandKit.

    Returns an HttpResponse to short-circuit the generic advance (route
    "zero" sends the merchant to the start-from-zero wizard; "existing"
    without a brand name stays on the step), or None to advance normally.
    """
    from apps.themes.models import BrandKit
    from apps.themes.validation import validate_palette

    route = request.POST.get("route", "").strip()
    brand_name = request.POST.get("brand_name", "").strip()
    if route == "zero" and not brand_name:
        from apps.generator.models import StoreBlueprint

        shop.onboarding_route = "zero"
        shop.save(update_fields=["onboarding_route"])
        StoreBlueprint.objects.get_or_create(
            shop=shop,
            status="brief",
            defaults={"onboarding_route": "zero"},
        )
        qs = request.GET.urlencode()
        target = "/app/start/"
        if qs:
            target = f"{target}?{qs}"
        return redirect(target)
    if route == "existing":
        shop.onboarding_route = "existing"
        shop.save(update_fields=["onboarding_route"])

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

    if not brand_name and shop.onboarding_route == "existing":
        # Route stored; wait for the BrandKit form submission before advancing
        return redirect("/app/onboarding/brand/")

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
                "tagline": request.POST.get("tagline", "").strip(),
            },
        )
        if shop.onboarding_route == "zero":
            # F15-5: the wizard continues with product ideas (T-114).
            from apps.generator.models import BlueprintStatus, StoreBlueprint
            from apps.themes.tasks import sync_brand_tokens

            bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
            if bp is not None:
                bp.palette = palette
                bp.fonts = {"heading": font_heading, "body": font_body}
                bp.status = BlueprintStatus.IDEAS
                done = list(bp.completed_steps or [])
                if "brand" not in done:
                    done.append("brand")
                bp.completed_steps = done
                bp.save(
                    update_fields=[
                        "palette",
                        "fonts",
                        "status",
                        "completed_steps",
                        "updated_at",
                    ]
                )
            sync_brand_tokens.delay(shop.id)  # F05-5 design tokens
            if bp is not None:
                from apps.generator.tasks import generate_product_ideas

                generate_product_ideas.delay(str(bp.id))  # F15-6
            qs = request.GET.urlencode()
            target = "/app/start/"
            if qs:
                target = f"{target}?{qs}"
            return redirect(target)


def _brand_step_extras(shop: Shop, request: HttpRequest) -> dict | HttpResponse:
    """Zero-route brand step: proposal state for the template.

    Redirects to the wizard once the brand is saved (status ideas);
    enqueues the niche_brand call while the proposal is missing.
    """
    from apps.generator.models import BlueprintStatus, StoreBlueprint
    from apps.generator.tasks import generate_brand_proposal

    bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
    if bp is None:
        return {}
    if bp.status == BlueprintStatus.IDEAS:
        qs = request.GET.urlencode()
        target = "/app/start/"
        if qs:
            target = f"{target}?{qs}"
        return redirect(target)
    proposal = bp.brand_proposal
    if bp.status == BlueprintStatus.BRAND and proposal is None:
        # The task no-ops when a proposal already exists (double-enqueue safe).
        generate_brand_proposal.delay(str(bp.id))
    from apps.themes.models import Tone
    from apps.themes.presets import get_preset_names

    return {
        "bp": bp,
        "proposal": proposal,
        "tones": [t.value for t in Tone],
        "presets": get_preset_names(),
    }


def _base_context(request: HttpRequest) -> dict:
    """Shared template context (App Bridge key, shop domain, locale)."""
    from django.conf import settings

    return {
        "shopify_api_key": settings.SHOPIFY_API_KEY,
        "shop_domain": getattr(request, "shop_domain", ""),
        "ui_locale": getattr(request, "ui_locale", "en"),
    }


def _get_shop(request: HttpRequest) -> Shop | None:
    """Get the shop from the request (populated by SessionTokenMiddleware)."""
    shop_domain = getattr(request, "shop_domain", None)
    if shop_domain:
        return Shop.objects.filter(domain=shop_domain).first()
    return None


def _redirect_to_dashboard() -> HttpResponse:
    """Redirect to the dashboard."""
    from django.http import HttpResponseRedirect

    return HttpResponseRedirect("/app/dashboard/")


def _redirect_to_onboarding(step: str) -> HttpResponse:
    """Redirect to an onboarding step."""
    from django.http import HttpResponseRedirect

    return HttpResponseRedirect(f"/app/onboarding/{step}/")
