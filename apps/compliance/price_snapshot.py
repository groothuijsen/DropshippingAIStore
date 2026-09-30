"""Price snapshot functionality for Omnibus compliance.

See docs/03-shopify-integration.md §6 step 4, docs/07-compliance.md §1.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

BULK_OPERATION_THRESHOLD = 250  # Use bulk operations for shops with more products


def _get_client(shop_domain: str, access_token: str) -> ShopifyGraphQLClient:
    """Create a GraphQL client for price snapshot operations."""
    from django.conf import settings

    return ShopifyGraphQLClient(shop_domain, access_token, settings.SHOPIFY_API_VERSION)


def snapshot_prices_small_shop(shop: Shop, access_token: str) -> int:
    """Snapshot prices for shops with ≤ 250 active products.

    Uses paginated product queries.
    Returns the number of PriceHistory rows created.
    """
    client = _get_client(shop.domain, access_token)
    created = 0
    now = timezone.now()

    try:
        has_next = True
        after_cursor: str | None = None

        while has_next:
            variables: dict[str, Any] = {"first": 50}
            if after_cursor:
                variables["after"] = after_cursor

            query = load_query("products_variants")
            data = client.execute(query, variables)

            products = data.get("products", {})
            page_info = products.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            after_cursor = page_info.get("endCursor")

            for product in products.get("nodes", []):
                for variant in product.get("variants", {}).get("nodes", []):
                    variant_gid = variant["id"]
                    price_str = variant.get("price", "0")
                    currency = shop.currency_code

                    try:
                        price = Decimal(price_str)
                    except (InvalidOperation, TypeError):
                        logger.warning("Invalid price %s for variant %s", price_str, variant_gid)
                        continue

                    # Check if this price differs from the last recorded price
                    from apps.compliance.models import PriceHistory

                    last = (
                        PriceHistory.objects.filter(
                            shop=shop,
                            variant_gid=variant_gid,
                            market_handle="primary",
                        )
                        .order_by("-observed_at")
                        .first()
                    )

                    if last and last.price == price:
                        continue  # Same price, no new row

                    PriceHistory.objects.create(
                        shop=shop,
                        variant_gid=variant_gid,
                        market_handle="primary",
                        price=price,
                        currency=currency,
                        observed_at=now,
                        source="install_snapshot",
                    )
                    created += 1

        logger.info("Price snapshot for %s: %d variants recorded", shop.domain, created)
        return created
    finally:
        client.close()


def snapshot_prices_bulk(shop: Shop, access_token: str) -> int:
    """Snapshot prices for shops with > 250 active products.

    Uses bulk operations to fetch all products.
    Returns the number of PriceHistory rows created.
    """
    client = _get_client(shop.domain, access_token)
    now = timezone.now()

    try:
        # Start bulk operation
        bulk_query = load_query("bulk_operation_run_query")
        gql = """
        {
            products(query: "status:active", first: 50) {
                edges {
                    node {
                        id
                        variants(first: 100) {
                            edges {
                                node {
                                    id
                                    price
                                    currencyCode
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        bulk_data = client.execute(bulk_query, {"query": gql})
        bulk_errors = bulk_data.get("bulkOperationRunQuery", {}).get("userErrors", [])
        if bulk_errors:
            logger.error("Bulk operation failed for %s: %s", shop.domain, bulk_errors)
            return 0

        bulk_id = bulk_data["bulkOperationRunQuery"]["bulkOperation"]["id"]

        # Poll until completed (max 10 minutes)
        poll_query = load_query("current_bulk_operation")
        for _ in range(120):  # 120 * 5s = 600s = 10 min
            import time

            time.sleep(5)
            poll_data = client.execute(poll_query, {"id": bulk_id})
            status_data = poll_data.get("currentBulkOperation", {})
            status = status_data.get("status", "")

            if status == "COMPLETED":
                url = status_data.get("url", "")
                if not url:
                    logger.warning("Bulk operation completed but no URL for %s", shop.domain)
                    return 0
                break
            elif status in ("FAILED", "CANCELED"):
                logger.error("Bulk operation %s for %s: %s", status, shop.domain, status_data.get("errorCode"))
                return 0
        else:
            logger.error("Bulk operation timed out for %s", shop.domain)
            return 0

        # Download and parse JSONL
        import httpx

        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()

        from apps.compliance.models import PriceHistory

        created = 0
        for line in resp.text.strip().split("\n"):
            if not line:
                continue
            row = json.loads(line)
            # Skip mutation errors
            if row.get("__typename") == "UserError":
                continue

            product = row.get("data", row)
            variants = product.get("variants", {}).get("edges", [])

            for variant_edge in variants:
                variant = variant_edge.get("node", {})
                variant_gid = variant.get("id", "")
                price_str = variant.get("price", "0")
                currency = variant.get("currencyCode", shop.currency_code)

                try:
                    price = Decimal(price_str)
                except (InvalidOperation, TypeError):
                    continue

                # Check last recorded price
                last = (
                    PriceHistory.objects.filter(
                        shop=shop,
                        variant_gid=variant_gid,
                        market_handle="primary",
                    )
                    .order_by("-observed_at")
                    .first()
                )

                if last and last.price == price:
                    continue

                PriceHistory.objects.create(
                    shop=shop,
                    variant_gid=variant_gid,
                    market_handle="primary",
                    price=price,
                    currency=currency,
                    observed_at=now,
                    source="install_snapshot",
                )
                created += 1

        logger.info("Bulk price snapshot for %s: %d variants recorded", shop.domain, created)
        return created
    finally:
        client.close()


def snapshot_prices(shop: Shop, access_token: str) -> int:
    """Snapshot prices for all active products. Uses small shop approach.

    For shops with >250 products, bulk operations would be more efficient,
    but the small shop paginated approach works for all sizes in the MVP.

    Returns the number of PriceHistory rows created.
    """
    return snapshot_prices_small_shop(shop, access_token)
