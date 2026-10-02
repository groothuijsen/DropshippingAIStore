"""Store go-live + undo (T-118, F15-12..14, 12 §2.3).

- ``publish_collections``: ``publishablePublish`` each blueprint
  collection to the Online Store publication (created unpublished in
  T-117; publishing happens only here).
- ``publish_store``: run the F07 page go-live per blueprint page whose
  preconditions are met; pages that fail are listed with reasons
  (incl. ``BUSINESS_DETAILS_MISSING`` for returns). Result stored on
  ``StoreBlueprint.publish_result`` + ``AuditLog``.
- ``undo_store_build``: delete the blueprint's collections, the
  ``mosaiq-main`` menu and its non-live pages; live pages block the undo
  and must be archived first (F15-14). Products and the BrandKit are
  never touched. Every deletion is logged in ``AuditLog``.
"""

from __future__ import annotations

import logging

from apps.core.shopify_client import load_query
from apps.generator.models import ManagedResource, Page, PageStatus

logger = logging.getLogger(__name__)

ONLINE_STORE_PUBLICATION = "Online Store"
# F15-9/13: page types whose go-live needs complete BusinessDetails
BUSINESS_DETAILS_PAGE_TYPES = {"returns"}


def _get_client(shop):
    from django.conf import settings

    from apps.core.shopify_client import ShopifyGraphQLClient
    from apps.core.tokens import decrypt_token

    return ShopifyGraphQLClient(
        shop.domain,
        decrypt_token(shop.access_token_encrypted),
        settings.SHOPIFY_API_VERSION,
    )


def get_online_store_publication_id(client) -> str:
    """Resolve the Online Store publication id (03 §4)."""
    data = client.execute(load_query("publications"))
    nodes = (data.get("publications") or {}).get("nodes") or []
    for node in nodes:
        if node.get("name") == ONLINE_STORE_PUBLICATION:
            return node["id"]
    raise RuntimeError("Online Store publication not found for this shop")


def publish_collections(client, bp) -> list[str]:
    """Publish every active blueprint collection (idempotent per run)."""
    publication_id = get_online_store_publication_id(client)
    published: list[str] = []
    collections = ManagedResource.objects.filter(
        shop=bp.shop, blueprint=bp, kind=ManagedResource.Kind.COLLECTION, removed_at__isnull=True
    )
    for mr in collections:
        data = client.execute(
            load_query("publishable_publish"),
            variables={"id": mr.gid, "input": [{"publicationId": publication_id}]},
        )
        errors = (data.get("publishablePublish") or {}).get("userErrors") or []
        if errors:
            raise RuntimeError(f"publishablePublish failed for {mr.handle}: {errors[0].get('message')}")
        published.append(mr.gid)
    return published


def _business_details_missing(page: Page) -> list[str]:
    try:
        details = page.shop.business_details
    except Exception:  # OneToOne reverse: absent row
        details = None
    if details is None:
        return ["BUSINESS_DETAILS_MISSING: legal_name, street, postal_code, city"]
    missing = details.is_complete("returns")
    if missing:
        return ["BUSINESS_DETAILS_MISSING: " + ", ".join(missing)]
    return []


def publish_store(bp) -> dict:
    """F15-13: publish collections + go live for every eligible page."""
    from apps.core.models import AuditLog
    from apps.generator.go_live import check_can_go_live, go_live

    if bp.build_job_id is None:
        return {}

    client = _get_client(bp.shop)
    result: dict = {"published_pages": {}, "blocked_pages": [], "collections_published": []}

    # Collections first — publishing them is safe regardless of pages.
    result["collections_published"] = publish_collections(client, bp)

    pages = Page.objects.filter(job__parent=bp.build_job).exclude(status=PageStatus.ARCHIVED)
    import sys
    for page in pages:
        reasons: list[str] = []
        if page.page_type in BUSINESS_DETAILS_PAGE_TYPES:
            reasons.extend(_business_details_missing(page))
        if not reasons:
            allowed, missing = check_can_go_live(page)
            if not allowed:
                reasons.extend(missing)
        if reasons:
            entry = {"page_type": page.page_type, "reasons": reasons}
            if page.product_gid:
                # Lets the build panel link straight to the GPSR form (T-161).
                entry["product_gid"] = page.product_gid
            result["blocked_pages"].append(entry)
            continue
        try:
            go_live(page)
        except (ValueError, RuntimeError) as exc:
            entry = {"page_type": page.page_type, "reasons": [str(exc)]}
            if page.product_gid:
                entry["product_gid"] = page.product_gid
            result["blocked_pages"].append(entry)
            continue
        page.refresh_from_db()
        result["published_pages"][page.page_type] = {
            "status": page.status,
            "gid": page.shopify_page_gid,
        }

    print("DEBUG final:", result, file=sys.stderr)
    bp.publish_result = result
    bp.save(update_fields=["publish_result", "updated_at"])
    AuditLog.objects.create(
        shop=bp.shop,
        actor="system",
        action="store_publish",
        payload={
            "blueprint_id": str(bp.id),
            "published": list(result["published_pages"]),
            "blocked": [b["page_type"] for b in result["blocked_pages"]],
            "collections": result["collections_published"],
        },
    )
    logger.info("Store publish for %s: %s", bp.id, result)
    return result


def undo_store_build(bp) -> dict:
    """F15-14: delete this blueprint's collections, menu and draft pages."""
    from apps.core.models import AuditLog

    result: dict = {"blocked": [], "deleted": {"collections": 0, "menu": 0, "pages": 0}}

    live_pages = Page.objects.filter(job__parent=bp.build_job, status=PageStatus.LIVE) if bp.build_job_id else Page.objects.none()
    if live_pages.exists():
        result["blocked"] = [
            {"page_type": p.page_type, "reasons": ["LIVE_PAGE — archive the page before undoing the build"]}
            for p in live_pages
        ]
        return result

    client = _get_client(bp.shop)
    resources = ManagedResource.objects.filter(
        shop=bp.shop, blueprint=bp, removed_at__isnull=True
    ).order_by("kind")

    for mr in resources:
        if mr.kind == ManagedResource.Kind.COLLECTION:
            data = client.execute(load_query("collection_delete"), variables={"input": {"id": mr.gid}})
            errors = (data.get("collectionDelete") or {}).get("userErrors") or []
        elif mr.kind == ManagedResource.Kind.MENU:
            data = client.execute(load_query("menu_delete"), variables={"id": mr.gid})
            errors = (data.get("menuDelete") or {}).get("userErrors") or []
        elif "/Metaobject/" in mr.gid:
            # Metaobject-only page (home): delete the metaobject, not a page.
            data = client.execute(load_query("metaobject_delete"), variables={"id": mr.gid})
            errors = (data.get("metaobjectDelete") or {}).get("userErrors") or []
        else:  # page
            data = client.execute(load_query("page_delete"), variables={"id": mr.gid})
            errors = (data.get("pageDelete") or {}).get("userErrors") or []
        if errors:
            # Keep the row active so a retry can pick it up again.
            logger.error("Undo delete failed for %s %s: %s", mr.kind, mr.handle, errors[0].get("message"))
            result.setdefault("failed", []).append({"kind": mr.kind, "handle": mr.handle, "error": errors[0].get("message")})
            continue
        from django.utils import timezone

        mr.removed_at = timezone.now()
        mr.save(update_fields=["removed_at"])
        if mr.kind == ManagedResource.Kind.PAGE:
            Page.objects.filter(shopify_page_gid=mr.gid, shop=bp.shop).update(status=PageStatus.ARCHIVED)
            result["deleted"]["pages"] += 1
        elif mr.kind == ManagedResource.Kind.COLLECTION:
            result["deleted"]["collections"] += 1
        else:
            result["deleted"]["menu"] += 1
        AuditLog.objects.create(
            shop=bp.shop,
            actor="system",
            action="store_undo",
            payload={"blueprint_id": str(bp.id), "kind": mr.kind, "gid": mr.gid, "handle": mr.handle},
        )

    logger.info("Undo store build for %s: %s", bp.id, result)
    return result
