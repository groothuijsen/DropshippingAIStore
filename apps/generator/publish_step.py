"""Publish step — publishes Page as draft in Shopify.

See docs/05-ai-pipeline.md §4.6.
Order:
1. GPSR check (incomplete → GPSR_INCOMPLETE, no write actions)
2. Per language metaobject_upsert (status DRAFT)
3. For landing/advertorial/listicle/about: page_create or page_update (isPublished:false)
4. Set metafield 'page' (list with all language entries) on product/page/shop
5. Page.version += 1, store GIDs
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from apps.compliance.gpsr import check_gpsr_for_publish
from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop
    from apps.generator.models import GenerationJob, JobStep, Page

logger = logging.getLogger(__name__)

# Metaobject type for Mosaiq pages
METAOBJECT_TYPE = "mosaiq_page"


def _get_client(shop: Shop) -> ShopifyGraphQLClient:
    """Get a ShopifyGraphQLClient for the shop."""
    from apps.core.crypto import decrypt_token

    token = decrypt_token(shop.access_token_encrypted)
    return ShopifyGraphQLClient(
        shop_domain=shop.domain,
        access_token=token,
        api_version="2026-07",
    )


def _upsert_metaobject(
    client: ShopifyGraphQLClient,
    handle: str,
    fields: dict[str, str],
    status: str = "DRAFT",
) -> str | None:
    """Upsert a metaobject. Returns metaobject GID or None."""
    field_list = [{"key": k, "value": v} for k, v in fields.items()]

    data = client.execute(
        load_query("metaobject_upsert"),
        variables={
            "handle": handle,
            "type": METAOBJECT_TYPE,
            "fields": field_list,
            "status": status,
        },
    )

    metaobject = data.get("metaobjectUpsert", {}).get("metaobject", {})
    return metaobject.get("id")


def _create_or_update_page(
    client: ShopifyGraphQLClient,
    page: Page,
    title: str,
    handle: str,
    template_suffix: str | None,
) -> str | None:
    """Create or update a Shopify page. Returns page GID or None."""
    if page.shopify_page_gid:
        # Update existing page
        data = client.execute(
            load_query("page_update"),
            variables={
                "id": page.shopify_page_gid,
                "page": {
                    "title": title,
                    "handle": handle,
                    "templateSuffix": template_suffix,
                    "isPublished": False,
                },
            },
        )
        page_data = data.get("pageUpdate", {}).get("page", {})
        return page_data.get("id")
    else:
        # Create new page
        data = client.execute(
            load_query("page_create"),
            variables={
                "page": {
                    "title": title,
                    "handle": handle,
                    "templateSuffix": template_suffix,
                    "isPublished": False,
                },
            },
        )
        page_data = data.get("pageCreate", {}).get("page", {})
        return page_data.get("id")


def run_publish(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Run the publish step for a job.

    1. GPSR check (incomplete → GPSR_INCOMPLETE, no write actions)
    2. Per language metaobject_upsert (status DRAFT)
    3. For landing/advertorial/listicle/about: page_create or page_update
    4. Set metafield 'page' on product/page/shop
    5. Page.version += 1, store GIDs
    """
    from apps.compliance.gpsr import GpsrInfo
    from apps.generator.layout_step import PAGE_TYPES_NEEDING_SHOPIFY_PAGE
    from apps.generator.models import Page

    # Find the page for this job
    page = Page.objects.filter(job=job).first()
    if not page:
        logger.error("No page found for job %s", job.id)
        return None

    # Load GPSR info from product metafield (or use defaults for now)
    # TODO: Load from product metafield when GPSR form is implemented
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

    # GPSR check first (05 §4.6)
    allowed, message = check_gpsr_for_publish(gpsr)
    if not allowed:
        from apps.generator.errors import GpsrIncomplete

        raise GpsrIncomplete(message)

    client = _get_client(job.shop)
    try:
        # Build metaobject fields from layout step output
        layout_step = job.steps.filter(name="layout", status="succeeded").first()
        if not layout_step or not layout_step.output:
            logger.error("No layout step output for job %s", job.id)
            return None

        fields = layout_step.output.get("metaobject_fields", {})
        template_suffix = layout_step.output.get("template_suffix")

        # Generate handle for metaobject
        locale = page.content_locale
        short_id = str(page.id)[:8]
        handle = f"mq-{page.page_type}-{short_id}-{locale}"

        # 1. Metaobject upsert (DRAFT)
        metaobject_gid = _upsert_metaobject(client, handle, fields, status="DRAFT")
        if not metaobject_gid:
            logger.error("Metaobject upsert failed for %s", handle)
            return None

        # 2. Create/update Shopify page for landing/advertorial/listicle/about
        shopify_page_gid = None
        if page.page_type in PAGE_TYPES_NEEDING_SHOPIFY_PAGE:
            shopify_page_gid = _create_or_update_page(
                client,
                page,
                title=page.title,
                handle=handle,
                template_suffix=template_suffix,
            )

        # 3. Set metafield 'page' on product/page/shop
        from apps.core.shopify_client import load_query

        metafield_owner = shopify_page_gid or page.shopify_page_gid
        if metafield_owner:
            try:
                query = load_query("metafields_set")
                metafield_value = json.dumps(
                    {
                        "metaobject_gids": page.metaobject_gids,
                        "metaobject_handles": page.metaobject_handles,
                    }
                )
                variables = {
                    "input": [
                        {
                            "ownerId": metafield_owner,
                            "namespace": "$app:mosaiq",
                            "key": "page",
                            "type": "json",
                            "value": metafield_value,
                        }
                    ]
                }
                client.execute(query, variables)
                logger.info("Metafield 'page' set on %s", metafield_owner)
            except Exception as exc:
                logger.warning("Failed to set metafield: %s", exc)

        # 4. Update Page model
        page.shopify_page_gid = shopify_page_gid or page.shopify_page_gid
        page.metaobject_gids[locale] = metaobject_gid
        page.metaobject_handles[locale] = handle
        page.version += 1
        page.save(update_fields=["shopify_page_gid", "metaobject_gids", "metaobject_handles", "version"])

        output = {
            "page_id": str(page.id),
            "metaobject_gid": metaobject_gid,
            "metaobject_handle": handle,
            "shopify_page_gid": shopify_page_gid,
            "template_suffix": template_suffix,
            "version": page.version,
        }

        return output

    except Exception as e:
        logger.warning("Publish failed for job %s: %s", job.id, e)
        raise

    finally:
        client.close()
