"""Variant locations — reads fulfillment location for source detection.

See docs/06-dropship-integrations.md §4.1, docs/03-shopify-integration.md §5.
Uses the variant_locations GraphQL query (scope: read_inventory).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)


def _get_client(shop: Shop, access_token: str) -> ShopifyGraphQLClient:
    from django.conf import settings

    return ShopifyGraphQLClient(shop.domain, access_token, settings.SHOPIFY_API_VERSION)


def get_variant_locations(
    shop: Shop,
    access_token: str,
    product_gid: str,
) -> list[dict[str, Any]]:
    """Read fulfillment location data for all variants of a product.

    Returns a list of dicts with variant_id, sku, and location info.
    Used as the strongest signal for source detection (06 §4.1).
    """
    client = _get_client(shop, access_token)

    try:
        query = load_query("variant_locations")
        # product_id:<id> uses the numeric ID, not the full GID
        numeric_id = product_gid.split("/")[-1]
        data = client.execute(query, {"query": f"product_id:{numeric_id}", "first": 100})
    finally:
        client.close()

    variants = data.get("productVariants", {}).get("nodes", [])
    results: list[dict[str, Any]] = []

    for variant in variants:
        inventory_item = variant.get("inventoryItem") or {}
        levels = inventory_item.get("inventoryLevels", {}).get("nodes", [])

        locations: list[dict[str, Any]] = []
        for level in levels:
            location = level.get("location") or {}
            fulfillment_service = location.get("fulfillmentService") or {}
            locations.append(
                {
                    "name": location.get("name", ""),
                    "is_fulfillment_service": location.get("isFulfillmentService", False),
                    "fulfillment_handle": fulfillment_service.get("handle", ""),
                    "fulfillment_service_name": fulfillment_service.get("serviceName", ""),
                }
            )

        results.append(
            {
                "variant_id": variant.get("id", ""),
                "sku": variant.get("sku", ""),
                "tracked": inventory_item.get("tracked", False),
                "locations": locations,
            }
        )

    return results


def extract_fulfillment_signals(variant_data: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Extract fulfillment_handle and location_name from variant data.

    Returns (fulfillment_handle, location_name) — the strongest signals
    for source detection.
    """
    fulfillment_handle: str | None = None
    location_name: str | None = None

    for variant in variant_data:
        for loc in variant.get("locations", []):
            if loc.get("fulfillment_handle") and not fulfillment_handle:
                fulfillment_handle = loc["fulfillment_handle"]
            if loc.get("name") and not location_name:
                location_name = loc["name"]

    return fulfillment_handle, location_name
