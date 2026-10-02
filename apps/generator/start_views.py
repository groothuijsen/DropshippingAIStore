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

    from apps.core.models import Shop

from apps.ai.schemas import NicheBrief
from apps.generator.models import BlueprintStatus, StoreBlueprint
from apps.generator.tasks import (
    generate_brand_proposal,
    generate_standard_pages,
    generate_store_structure,
)
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

        if bp.status == BlueprintStatus.IDEAS and action == "start_import":
            from django.utils import timezone

            # F15-6/§2.2: first click wins — the import window stays stable
            # even if the merchant re-opens the app later (T-115 lists
            # products created after this moment).
            if bp.started_products_at is None:
                bp.started_products_at = timezone.now()
                bp.save(update_fields=["started_products_at", "updated_at"])
                messages.success(
                    request,
                    "Import your products — newly created products appear in the next step.",
                )
            return redirect(back)

        if bp.status == BlueprintStatus.IDEAS and action == "select_products":
            gids = request.POST.getlist("product_gid")
            max_products = _plan_limits(shop)["products_per_build"]
            if not gids:
                messages.error(
                    request,
                    "Select at least one product before continuing. (BLUEPRINT_NO_PRODUCTS)",
                )
                return redirect(back)
            if len(gids) > max_products:
                messages.error(
                    request,
                    f"Your plan allows {max_products} products per store build.",
                )
                return redirect(back)
            bp.selected_product_gids = gids
            bp.status = BlueprintStatus.STRUCTURE
            done = list(bp.completed_steps or [])
            if "ideas" not in done:
                done.append("ideas")
            bp.completed_steps = done
            bp.save(
                update_fields=[
                    "selected_product_gids",
                    "status",
                    "completed_steps",
                    "updated_at",
                ]
            )
            generate_store_structure.delay(str(bp.id))
            messages.success(request, f"{len(gids)} products selected.")
            return redirect(back)

    if bp.status == BlueprintStatus.STRUCTURE and bp.store_structure:
        from django.contrib import messages

        action = request.POST.get("action", "")
        structure = bp.store_structure

        def _save_structure() -> None:
            bp.store_structure = structure
            bp.save()

        def _list_for(item_type: str) -> list:
            return structure.get("collections" if item_type == "collection" else "menu", [])

        if action == "structure_rename":
            item_type = request.POST.get("item_type", "")
            field = request.POST.get("field", "")
            value = (request.POST.get("value") or "").strip()
            try:
                idx = int(request.POST.get("index", "-1"))
            except ValueError:
                idx = -1
            items = _list_for(item_type)
            max_len = (
                60
                if item_type == "collection" and field == "title"
                else 300
                if item_type == "collection"
                else 40
            )
            if 0 <= idx < len(items) and field in {"title", "description"} and value:
                new_value = value[:max_len]
                if item_type == "collection" and field == "title":
                    # Keep menu refs consistent: items pointing at the old
                    # collection title follow the rename (F15-8 confirm
                    # validates refs against collection titles).
                    old_title = items[idx]["title"]
                    for menu_item in structure.get("menu", []):
                        if menu_item.get("target") == "collection" and menu_item.get("ref") == old_title:
                            menu_item["ref"] = new_value
                items[idx][field] = new_value
                _save_structure()
        elif action == "structure_move":
            item_type = request.POST.get("item_type", "")
            direction = request.POST.get("dir", "")
            try:
                idx = int(request.POST.get("index", "-1"))
            except ValueError:
                idx = -1
            items = _list_for(item_type)
            target = idx - 1 if direction == "up" else idx + 1
            if 0 <= idx < len(items) and 0 <= target < len(items):
                items[idx], items[target] = items[target], items[idx]
                _save_structure()
        elif action == "structure_delete":
            item_type = request.POST.get("item_type", "")
            try:
                idx = int(request.POST.get("index", "-1"))
            except ValueError:
                idx = -1
            if item_type == "page":
                pages = structure.get("pages", [])
                if 0 <= idx < len(pages) and len(pages) > 2:
                    pages.pop(idx)
                    _save_structure()
                else:
                    messages.error(request, "A store needs at least 2 pages.")
            else:
                items = _list_for(item_type)
                minimum = 1 if item_type == "collection" else 3
                label = "collection" if item_type == "collection" else "menu item"
                if 0 <= idx < len(items) and len(items) > minimum:
                    items.pop(idx)
                    _save_structure()
                else:
                    messages.error(request, f"A store needs at least {minimum} {label}s.")
        elif action == "structure_add_collection":
            title = (request.POST.get("title") or "").strip()
            description = (request.POST.get("description") or "").strip()
            gids = request.POST.getlist("product_gid")
            selection = set(bp.selected_product_gids or [])
            if not title:
                messages.error(request, "The collection needs a title.")
            elif len(structure.get("collections", [])) >= 6:
                messages.error(request, "A store can have at most 6 collections.")
            elif not gids or any(g not in selection for g in gids):
                messages.error(request, "Pick at least one product from your selection.")
            else:
                structure["collections"].append(
                    {"title": title[:60], "description": description[:300], "product_gids": gids[:20]}
                )
                _save_structure()
        elif action == "structure_add_page":
            page_type = request.POST.get("page_type", "")
            allowed = {"about", "faq", "shipping", "returns"}
            if page_type not in allowed:
                messages.error(request, "Unknown page type.")
            elif page_type in structure.get("pages", []):
                messages.error(request, "That page is already in the structure.")
            elif len(structure.get("pages", [])) >= 4:
                messages.error(request, "A store can have at most 4 standard pages.")
            else:
                structure["pages"].append(page_type)
                _save_structure()
        elif action == "structure_retry":
            bp.structure_error = ""
            bp.save(update_fields=["structure_error", "updated_at"])
            generate_store_structure.delay(str(bp.id))
            return redirect("/app/start/?id_token=" + request.GET.get("id_token", ""))
        elif action == "structure_confirm":
            selection = set(bp.selected_product_gids or [])
            covered = {g for c in structure.get("collections", []) for g in c.get("product_gids", [])}
            missing_products = selection - covered
            pages = structure.get("pages", [])
            collection_titles = {c.get("title", "") for c in structure.get("collections", [])}
            unresolved = [
                m.get("title", "?")
                for m in structure.get("menu", [])
                if m.get("target") == "collection" and m.get("ref") not in collection_titles
            ]
            problems = []
            if missing_products:
                problems.append("Every selected product must sit in at least one collection.")
            if "shipping" not in pages or "returns" not in pages:
                problems.append("The shipping and returns pages are required.")
            if unresolved:
                problems.append("Menu items point at missing collections: " + ", ".join(unresolved))
            if not 3 <= len(structure.get("menu", [])) <= 8:
                problems.append("A menu needs 3 to 8 items.")
            if problems:
                for problem in problems:
                    messages.error(request, problem)
            else:
                bp.store_structure = structure
                bp.structure_error = ""
                bp.completed_steps = sorted({*(bp.completed_steps or []), "structure"})
                bp.status = BlueprintStatus.BUILDING
                bp.save()
                generate_standard_pages.delay(str(bp.id))
                messages.success(request, "Store structure confirmed.")
                return redirect("/app/start/?id_token=" + request.GET.get("id_token", ""))

    if bp.status == BlueprintStatus.IDEAS and bp.product_ideas is None:
        from apps.generator.tasks import generate_product_ideas

        # Idempotent: the task no-ops when ideas already exist.
        generate_product_ideas.delay(str(bp.id))

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
            "import_app_display": _import_app_display(bp),
            "import_products": _import_products_context(shop, bp)
            if bp.status == BlueprintStatus.IDEAS
            else {},
            **(_structure_panel_context(bp) if bp.status == BlueprintStatus.STRUCTURE else {}),
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
    """HTMX fragment for the names or product-ideas panel (polled every 3s)."""
    shop = _get_shop(request)
    if shop is None:
        return _unauthorized()
    bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
    if bp is None:
        return _unauthorized()
    if bp.status == BlueprintStatus.IDEAS:
        return render(
            request,
            "app/start_ideas_panel.html",
            {
                "bp": bp,
                "import_app_display": _import_app_display(bp),
                "import_products": _import_products_context(shop, bp),
            },
        )

    if bp.status == BlueprintStatus.STRUCTURE:
        ctx = {"bp": bp}
        ctx.update(_structure_panel_context(bp))
        return render(request, "app/start_structure_panel.html", ctx)

    if bp.status == BlueprintStatus.BUILDING:
        return render(request, "app/start_build_panel.html", {"bp": bp})
    return render(
        request,
        "app/start_panel.html",
        {
            "bp": bp,
            "tmview_url": TMVIEW_URL,
            "max_regenerate": MAX_REGENERATE,
        },
    )


def _plan_limits(shop: Shop) -> dict:
    """Plan limits for the shop (12 §7); defaults to starter."""
    from apps.billing.models import Subscription
    from apps.billing.plans import get_plan_limits

    sub = Subscription.objects.filter(shop=shop).order_by("-created_at").first()
    plan = sub.plan if sub else "starter"
    return get_plan_limits(plan)


def _fetch_shop_products(shop: Shop) -> list[dict]:
    """Fallback products query for the import-waiting screen (F15-7)."""

    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query

    try:
        token = decrypt_token(shop.access_token_encrypted)
        client = ShopifyGraphQLClient(shop.domain, token, settings_api_version())
        data = client.execute(load_query("products_list"), {"first": 50})
        return (data.get("products") or {}).get("nodes") or []
    except Exception as exc:  # poll endpoint must never 500
        logger.warning("products query failed for %s: %s", shop.domain, exc)
        return []


def settings_api_version() -> str:
    from django.conf import settings

    return getattr(settings, "SHOPIFY_API_VERSION", "2026-07")


def _norm_gid(gid) -> str:
    """Webhooks deliver numeric IDs; the Admin API returns GIDs.

    str() guard: legacy webhook rows may hold the id as an int.
    """
    gid = str(gid or "")
    return f"gid://shopify/Product/{gid}" if gid.isdigit() else gid


def _structure_panel_context(bp: StoreBlueprint) -> dict:
    """Context for the structure panel: selected products + addable pages."""
    selected = {_norm_gid(g) for g in (bp.selected_product_gids or [])}
    products = []
    known = set()
    for item in bp.imported_products or []:
        gid = _norm_gid(item.get("gid", ""))
        if gid in selected:
            products.append({"gid": gid, "title": item.get("title") or gid})
            known.add(gid)
    for gid in sorted(selected - known):
        products.append({"gid": gid, "title": gid})
    existing = set((bp.store_structure or {}).get("pages", []))
    available = [t for t in ("about", "faq", "shipping", "returns") if t not in existing]
    return {"import_products_for_structure": products, "available_pages": available}


def _import_products_context(shop: Shop, bp: StoreBlueprint) -> dict:
    """Merged product list for the import-waiting screen (F15-7).

    Webhook-recorded products (fast signal) plus the fallback query,
    deduped by GID, split into 'new since the import window' and
    'existing'. Each row carries a vendor-based source detection (06).
    """
    from django.utils import timezone

    from apps.sources.rules import detect_source

    window = bp.started_products_at
    merged: dict[str, dict] = {}
    for item in bp.imported_products or []:
        gid = _norm_gid(item.get("gid", ""))
        merged[gid] = {
            "gid": gid,
            "title": item.get("title") or "(untitled)",
            "vendor": item.get("vendor") or "",
            "created_at": item.get("created_at") or "",
        }
    for node in _fetch_shop_products(shop):
        gid = node.get("id", "")
        if not gid:
            continue
        merged.setdefault(
            gid,
            {
                "gid": gid,
                "title": node.get("title") or "(untitled)",
                "vendor": node.get("vendor") or "",
                "created_at": node.get("createdAt") or "",
            },
        )

    def _parse(dt: str):
        if not dt:
            return None
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(dt)
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.utc)
        return parsed

    rows = []
    for item in merged.values():
        created = _parse(item["created_at"])
        source, _by = detect_source(
            vendor=item["vendor"] or None,
            onboarding_apps=[bp.import_app] if bp.import_app else None,
        )
        rows.append(
            {
                **item,
                "is_new": bool(window and created and created >= window),
                "source": source,
            }
        )
    rows.sort(key=lambda r: (not r["is_new"], r["title"].lower()))
    return {
        "products": rows,
        "max_products": _plan_limits(shop)["products_per_build"],
        "selected": list(bp.selected_product_gids or []),
    }


def _import_app_display(bp: StoreBlueprint) -> dict:
    """App name + deep link for the product-ideas screen (F15-6)."""
    from apps.generator.import_apps import import_app_link, import_app_name

    app = bp.import_app or "manual"
    return {
        "name": import_app_name(app),
        "link": import_app_link(app, (bp.description or "")[:60]),
    }
