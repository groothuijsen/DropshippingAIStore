"""Go live + archive — page lifecycle management.

See docs/specs/F07-pages.md criteria 4-8.
- Set live disabled given open blocks, incomplete GPSR, missing unit price
- Live pages limit checked before action
- Set live: metaobjects ACTIVE, page published, Page.status = live
- Archive: metaobject DRAFT, page unpublished, metafield deleted
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.compliance.gpsr import GpsrInfo, check_gpsr_for_publish
from apps.core.shopify_client import ShopifyGraphQLClient
from apps.generator.publish_step import METAOBJECT_TYPE

if TYPE_CHECKING:
    from apps.core.models import Shop
    from apps.generator.models import Page

logger = logging.getLogger(__name__)

# Page types that need a Shopify page — single source of truth lives in
# layout_step (T-116 added faq/shipping/returns).
from apps.generator.layout_step import PAGE_TYPES_NEEDING_SHOPIFY_PAGE  # noqa: E402,F401


def _get_client(shop: Shop) -> ShopifyGraphQLClient:
    """Get a ShopifyGraphQLClient for the shop."""
    from apps.core.crypto import decrypt_token

    token = decrypt_token(shop.access_token_encrypted)
    return ShopifyGraphQLClient(
        shop_domain=shop.domain,
        access_token=token,
        api_version="2026-07",
    )


def check_can_go_live(page: Page) -> tuple[bool, list[str]]:
    """Check if a page can go live (F07 criterion 4).

    Checks:
    1. Open block findings
    2. GPSR completeness
    3. Missing mandatory unit price
    4. Live pages limit

    Returns (allowed, missing_conditions).
    """
    from apps.compliance.claims import check_sections
    from apps.compliance.scoring import has_open_block
    from apps.generator.models import Page as PageModel

    missing: list[str] = []

    # 1. Check for open block findings
    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])

    findings = check_sections(sections, locale)
    if has_open_block(findings):
        missing.append("Open compliance blocks — edit highlighted text first")

    # 2. GPSR completeness — GPSR obligations attach to PRODUCTS
    # (manufacturer/safety data for the product); standard pages
    # (faq/shipping/returns/home) have no GPSR duty (T-118/F15-13 live
    # lesson: the empty-GpsrInfo check blocked every page).
    # TODO: Load from product metafield when GPSR form is implemented.
    if page.product_gid or page.page_type == "pdp":
        gpsr = GpsrInfo(
            manufacturer_name="",
            manufacturer_address="",
            manufacturer_email="",
            manufacturer_in_eu=True,
            eu_rp_name="",
            eu_rp_address="",
            eu_rp_email="",
            product_identifier="",
            warnings="",
            no_warnings_confirmed=False,
        )
        allowed, _msg = check_gpsr_for_publish(gpsr)
        if not allowed:
            missing.append("GPSR data incomplete — fill in manufacturer and safety details")

    # 3. Check unit price (TODO: implement when UnitPriceInfo is fully wired)
    # For now, skip — will be checked when unit price form is live

    # 3b. 30-day delivery rule (F18-7, CRD art. 18): any market with
    # max_days > 30 blocks go-live — beyond 30 days needs explicit
    # agreement with the consumer.
    if page.product_gid:
        from apps.compliance.delivery import estimate
        from apps.compliance.models import DeliveryProfile

        markets: set[str] = set()
        for prof in DeliveryProfile.objects.filter(shop=page.shop):
            markets |= set((prof.transit_days or {}).keys())
        for market in markets or {""}:
            est = estimate(page.shop, page.product_gid, market)
            if est is not None and est.over_30_days:
                missing.append(
                    "DELIVERY_OVER_30_DAYS — delivery exceeds 30 working days in "
                    f"market {market or 'default'}; needs explicit customer agreement"
                )
                break

    # 4. Check live pages limit
    from apps.billing.models import Subscription
    from apps.billing.plans import get_plan_limits

    try:
        subscription = Subscription.objects.get(shop=page.shop)
        plan = subscription.plan
    except Subscription.DoesNotExist:
        plan = "starter"

    limits = get_plan_limits(plan)
    live_limit = limits.get("live_pages")

    if live_limit is not None:
        current_live = PageModel.objects.filter(shop=page.shop, status="live").exclude(id=page.id).count()
        if current_live >= live_limit:
            missing.append(f"Live pages limit reached ({live_limit}) — upgrade your plan")

    return (len(missing) == 0, missing)


def go_live(page: Page) -> dict[str, Any]:
    """Set a page live (F07 criterion 5).

    1. Check conditions (blocks/GPSR/unit price/live limit)
    2. Metaobjects → ACTIVE
    3. Page → isPublished:true
    4. Page.status = live
    """
    from apps.core.shopify_client import load_query

    allowed, missing = check_can_go_live(page)
    if not allowed:
        raise ValueError(f"Cannot go live: {'; '.join(missing)}")

    client = _get_client(page.shop)
    try:
        # 1. Metaobjects → ACTIVE
        for locale, _handle in page.metaobject_handles.items():
            metaobject_gid = page.metaobject_gids.get(locale)
            if metaobject_gid:
                try:
                    query = load_query("metaobject_upsert")
                    # Update status to ACTIVE via metaobjectUpsert. fields is
                    # NON_NULL in 2026-07: send the current field values back
                    # so the upsert never wipes content.
                    variables = {
                        "handle": {"type": METAOBJECT_TYPE, "handle": _handle},
                        "metaobject": {
                            "fields": _current_metaobject_fields(client, metaobject_gid),
                            "capabilities": {"publishable": {"status": "ACTIVE"}},
                        },
                    }
                    client.execute(query, variables)
                    logger.info("Metaobject %s set ACTIVE for locale %s", _handle, locale)
                except Exception as exc:
                    logger.warning("Failed to set metaobject %s ACTIVE: %s", _handle, exc)

        # 2. Page → isPublished:true (for page types that have a Shopify page)
        if page.page_type in PAGE_TYPES_NEEDING_SHOPIFY_PAGE and page.shopify_page_gid:
            try:
                query = load_query("page_publish")
                # API 2026-07: pageUpdate(id: ID!, page: PageUpdateInput!)
                # — id is a top-level argument (introspected live).
                variables = {
                    "id": page.shopify_page_gid,
                    "page": {"isPublished": True},
                }
                data = client.execute(query, variables)
                errs = (data.get("pageUpdate") or {}).get("userErrors") or []
                if errs:
                    raise RuntimeError(f"pageUpdate failed: {errs[0].get('message')}")
                logger.info("Shopify page %s published", page.shopify_page_gid)
            except Exception as exc:
                # A page that could not be published must not be marked
                # live (F07-5 requires all three steps); abort so the
                # caller lists it as blocked (T-118 live lesson).
                raise RuntimeError(f"Shopify page publish failed: {exc}") from exc

        # 3. Update Page model
        page.status = "live"
        page.save(update_fields=["status"])

        output = {
            "page_id": str(page.id),
            "status": "live",
            "version": page.version,
        }

        logger.info("Page %s set live", page.id)
        return output

    finally:
        client.close()


def archive_page(page: Page) -> dict[str, Any]:
    """Archive a page (F07 criterion 8).

    1. Metaobjects → DRAFT
    2. Page unpublished
    3. Metafield deleted
    """
    from apps.core.shopify_client import load_query

    client = _get_client(page.shop)
    try:
        # 1. Metaobjects → DRAFT
        for locale, _handle in page.metaobject_handles.items():
            metaobject_gid = page.metaobject_gids.get(locale)
            if metaobject_gid:
                try:
                    query = load_query("metaobject_upsert")
                    variables = {
                        "handle": {"type": METAOBJECT_TYPE, "handle": _handle},
                        "metaobject": {
                            "fields": _current_metaobject_fields(client, metaobject_gid),
                            "capabilities": {"publishable": {"status": "DRAFT"}},
                        },
                    }
                    client.execute(query, variables)
                    logger.info("Metaobject %s set DRAFT for locale %s", _handle, locale)
                except Exception as exc:
                    logger.warning("Failed to set metaobject %s DRAFT: %s", _handle, exc)

        # 2. Page unpublished
        if page.page_type in PAGE_TYPES_NEEDING_SHOPIFY_PAGE and page.shopify_page_gid:
            try:
                query = load_query("page_publish")
                variables = {
                    "page": {
                        "id": page.shopify_page_gid,
                        "isPublished": False,
                    }
                }
                client.execute(query, variables)
                logger.info("Shopify page %s unpublished", page.shopify_page_gid)
            except Exception as exc:
                logger.warning("Failed to unpublish Shopify page: %s", exc)

        # 3. Metafield deleted
        if page.shopify_page_gid:
            try:
                query = load_query("metafields_delete")
                variables = {
                    "metafields": [{"ownerId": page.shopify_page_gid, "namespace": "$app:mosaiq", "key": "page"}]
                }
                client.execute(query, variables)
                logger.info("Metafield deleted for page %s", page.shopify_page_gid)
            except Exception as exc:
                logger.warning("Failed to delete metafield: %s", exc)

        # 4. Update Page model
        page.status = "archived"
        page.save(update_fields=["status"])

        output = {
            "page_id": str(page.id),
            "status": "archived",
        }

        logger.info("Page %s archived", page.id)
        return output

    finally:
        client.close()


def _current_metaobject_fields(client, metaobject_gid: str) -> list[dict]:
    """Fetch a metaobject's current key/value fields (2026-07 upserts must
    resend them — the fields argument is NON_NULL)."""
    from apps.core.shopify_client import load_query

    try:
        data = client.execute(load_query("metaobject_get"), variables={"id": metaobject_gid})
        metaobject = data.get("metaobject") or {}
        return [{"key": f["key"], "value": f["value"]} for f in metaobject.get("fields") or []]
    except Exception as exc:  # noqa: BLE001 — never block a status flip on a read
        logger.warning("Could not read metaobject %s fields: %s", metaobject_gid, exc)
        return []
