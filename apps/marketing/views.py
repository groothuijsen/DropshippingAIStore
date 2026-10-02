"""Marketing site views — host-guarded (F19-1, 13 §2 D-19.1)."""

from __future__ import annotations

import markdown
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.billing.plans import PLAN_LIMITS, PLAN_NAMES, PLAN_PRICES

from .content import LANGUAGES, load_page
from .freshness import annotate_comparisons
from .schemas import validate_sections

MARKETING_HOST = "shopify.mosaiq.marketing"
APP_HOST = "shop.mosaiq.marketing"


def _guard(request: HttpRequest) -> str | None:
    """Return the language for this request, None when the host must not
    serve marketing content (handled by the caller)."""
    host = request.get_host().split(":")[0]
    if host == APP_HOST:
        return "app"
    if host == MARKETING_HOST:
        return "en"
    return "deny"


@require_GET
def page_view(request: HttpRequest, slug: str = "home") -> HttpResponse:
    lang = "nl" if request.path.startswith("/nl/") else "en"
    mode = _guard(request)
    if mode == "app":
        if slug == "home" and not request.path.startswith("/nl/"):
            return HttpResponseRedirect("/app/")
        raise Http404
    if mode == "deny":
        raise Http404

    try:
        page = load_page(lang, slug)
    except FileNotFoundError:
        raise Http404 from None

    errors = validate_sections(page["sections"])
    if errors:
        raise Http404  # broken content never ships (check_marketing_content catches it in CI)

    annotate_comparisons(page["sections"])
    page["body_html"] = markdown.markdown(page["body"], extensions=["extra"]) if page["body"] else ""
    return render(request, page["template"], {
        "page": page, "lang": lang, "languages": LANGUAGES, "plans": _plans_context(page)})


def _plans_context(page: dict) -> list[dict]:
    """Pricing cards rendered from plans.py — prices are never typed in copy."""
    cards: list[dict] = []
    for slug, prices in PLAN_PRICES.items():
        limits = PLAN_LIMITS[slug]
        cards.append({
            "slug": slug,
            "name": PLAN_NAMES[slug],
            "monthly": f"${prices['every_30_days'].normalize()}",
            "annual": f"${prices['annual'].normalize()}",
            "blurb": page.get("blurbs", {}).get(slug, ""),
            "limits": [
                ("Store generations / 30 days", limits["store_generations"]),
                ("Live pages", limits["live_pages"] if limits["live_pages"] is not None else "Unlimited"),
                ("AI images / 30 days", limits["ai_images"]),
                ("Page edits / 30 days", limits["page_edits"]),
            ],
        })
    return cards


@require_GET
def blog_index(request: HttpRequest) -> HttpResponse:
    _mode = _guard(request)
    if _mode != "en" and not (request.path.startswith("/nl/") and _mode == "en"):
        raise Http404
    lang = "nl" if request.path.startswith("/nl/") else "en"
    return render(request, "marketing/page_default.html", {
        "page": {"title": "Blog", "slug": "/blog/", "description": "", "sections": [], "body": "", "lang": lang},
        "lang": lang, "languages": LANGUAGES,
    })
