"""Start-from-zero wizard (F15-1/3/4, T-112).

GET/POST /app/start/ — brief screen → name suggestions (Celery) → pick name.
Brand, product ideas, structure and build arrive with T-113..T-117.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.shortcuts import redirect, render

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

from apps.ai.schemas import NicheBrief
from apps.generator.models import BlueprintStatus, StoreBlueprint
from apps.generator.tasks import generate_brand_proposal
from apps.themes.brand_blocklist import is_blocked_brand

logger = logging.getLogger(__name__)

PRICE_LEVELS = ("budget", "mid", "premium")
MARKETS = ("NL", "BE", "DE", "AT", "FR", "LU", "GB", "IE", "OTHER_EU")
LOCALES = ("nl", "en", "de")
IMPORT_APPS = ("dsers", "cj", "zendrop", "autods", "printify", "printful", "manual", "other")
MAX_REGENERATE = 3
TMVIEW_URL = "https://euipo.europa.eu/eSearch/#basic/1+1+1+1/100+100+100+100+100+100+100+100+100+100"


def _get_shop(request: HttpRequest):
    from apps.core.models import Shop

    shop_domain = getattr(request, "shop_domain", None)
    return Shop.objects.filter(domain=shop_domain).first() if shop_domain else None


def start_wizard(request: HttpRequest) -> HttpResponse:
    """The start-from-zero wizard screen (12 §2.2, route 'zero')."""
    from django.contrib import messages

    shop = _get_shop(request)
    if shop is None:
        return _unauthorized()

    bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
    if bp is None:
        bp = StoreBlueprint.objects.create(shop=shop, status=BlueprintStatus.BRIEF)

    qs = request.GET.urlencode()
    back = f"/app/start/?{qs}" if qs else "/app/start/"

    if request.method == "POST":
        action = request.POST.get("action", "")

        if bp.status == BlueprintStatus.BRIEF and action in ("", "brief"):
            errors = _save_brief(bp, request)
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                from apps.generator.tasks import generate_name_suggestions

                bp.status = BlueprintStatus.NAMES
                bp.save(update_fields=["status", "updated_at"])
                generate_name_suggestions.delay(str(bp.id))
                messages.success(request, "Brief saved — generating name suggestions.")
            return redirect(back)

        if bp.status == BlueprintStatus.NAMES:
            if action == "regenerate":
                if bp.regenerate_count >= MAX_REGENERATE:
                    messages.error(
                        request,
                        f"Regenerate limit reached ({MAX_REGENERATE}). Pick one of the names or type your own.",
                    )
                else:
                    from apps.generator.tasks import generate_name_suggestions

                    bp.regenerate_count += 1
                    bp.name_suggestions = []
                    bp.save(update_fields=["regenerate_count", "name_suggestions", "updated_at"])
                    generate_name_suggestions.delay(str(bp.id))
                    messages.success(request, "Generating new suggestions.")
                return redirect(back)

            if action == "pick_own":
                name = request.POST.get("own_name", "").strip()
                reason = is_blocked_brand(name) if name else "Name is empty"
                if reason:
                    messages.error(request, f"'{name}' cannot be used: {reason}")
                else:
                    _pick_name(bp, name)
                    messages.success(request, f"Brand name '{name}' saved.")
                    return redirect("/app/onboarding/brand/?id_token=" + request.GET.get("id_token", ""))

            if action == "pick":
                idx = request.POST.get("pick_index", "")
                try:
                    item = bp.name_suggestions[int(idx)]
                except (ValueError, IndexError):
                    messages.error(request, "Invalid selection.")
                    return redirect(back)
                _pick_name(bp, item["name"])
                messages.success(request, f"Brand name '{item['name']}' saved.")
                return redirect("/app/onboarding/brand/?id_token=" + request.GET.get("id_token", ""))

    return render(
        request,
        "app/start_wizard.html",
        {
            "shopify_api_key": request_get_api_key(),
            "shop_domain": getattr(request, "shop_domain", ""),
            "ui_locale": getattr(request, "ui_locale", "en"),
            "shop": shop,
            "bp": bp,
            "markets": MARKETS,
            "locales": LOCALES,
            "import_apps": IMPORT_APPS,
            "price_levels": PRICE_LEVELS,
            "max_regenerate": MAX_REGENERATE,
            "tmview_url": TMVIEW_URL,
        },
    )


def request_get_api_key() -> str:
    from django.conf import settings

    return settings.SHOPIFY_API_KEY


def _unauthorized() -> HttpResponse:
    from django.http import HttpResponseForbidden

    return HttpResponseForbidden("Unauthorized")


def _pick_name(bp: StoreBlueprint, name: str) -> None:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    bp.brand_name = name
    bp.brand_slug = slug
    bp.status = BlueprintStatus.BRAND
    done = list(bp.completed_steps or [])
    if "names" not in done:
        done.append("names")
    bp.completed_steps = done
    bp.save(update_fields=["brand_name", "brand_slug", "status", "completed_steps", "updated_at"])
    generate_brand_proposal.delay(str(bp.id))  # F15-5: one niche_brand call


def _save_brief(bp: StoreBlueprint, request: HttpRequest) -> list[str]:
    """Validate the brief form against NicheBrief (F15-3). Nothing is sent
    to the AI until valid — enforced here because the names task only runs
    after this returns no errors."""
    data = {
        "description": request.POST.get("description", "").strip(),
        "markets": request.POST.getlist("markets"),
        "content_locales": request.POST.getlist("content_locales"),
        "audience": request.POST.get("audience", "").strip(),
        "price_level": request.POST.get("price_level", ""),
        "import_app": request.POST.get("import_app", ""),
    }
    try:
        brief = NicheBrief(**data)
    except Exception as exc:  # pydantic ValidationError
        errors: list[str] = []
        if hasattr(exc, "errors"):
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                errors.append(f"{loc}: {err.get('msg', 'invalid')}")
        else:
            errors.append(str(exc))
        return errors or ["Brief is invalid."]

    bp.description = brief.description
    bp.markets = list(brief.markets)
    bp.content_locales = list(brief.content_locales)
    bp.audience = brief.audience
    bp.price_level = brief.price_level
    bp.import_app = brief.import_app
    bp.niche_hint = request.POST.get("niche_hint", bp.niche_hint).strip()
    bp.free_text = request.POST.get("free_text", bp.free_text).strip()
    bp.save(
        update_fields=[
            "description",
            "markets",
            "content_locales",
            "audience",
            "price_level",
            "import_app",
            "niche_hint",
            "free_text",
            "updated_at",
        ]
    )
    return []


def start_panel(request: HttpRequest) -> HttpResponse:
    """HTMX fragment for the names panel (polled every 3s while generating)."""
    shop = _get_shop(request)
    if shop is None:
        return _unauthorized()
    bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
    if bp is None:
        return _unauthorized()
    return render(
        request,
        "app/start_panel.html",
        {
            "bp": bp,
            "tmview_url": TMVIEW_URL,
            "max_regenerate": MAX_REGENERATE,
        },
    )
