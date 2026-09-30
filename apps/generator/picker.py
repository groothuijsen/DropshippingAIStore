"""Product picker — paginated product list for the merchant.

See docs/specs/F01-import.md criterion 1.
50 per page, search field on title, source label per product.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


def _get_client(shop: Shop, access_token: str) -> ShopifyGraphQLClient:
    from django.conf import settings

    return ShopifyGraphQLClient(shop.domain, access_token, settings.SHOPIFY_API_VERSION)


def list_products(
    shop: Shop,
    access_token: str,
    *,
    search: str = "",
    page: int = 1,
) -> dict[str, Any]:
    """List products with pagination and source labels.

    Returns {products: [...], page: int, has_next: bool, total_pages: int}.
    """
    from apps.sources.models import ProductSource

    client = _get_client(shop, access_token)

    try:
        query = load_query("products_list")
        cursor = None
        all_products: list[dict[str, Any]] = []

        # Fetch up to page * PAGE_SIZE products
        target_count = page * PAGE_SIZE
        has_next = True

        while len(all_products) < target_count and has_next:
            variables: dict[str, Any] = {"first": PAGE_SIZE}
            if cursor:
                variables["after"] = cursor

            data = client.execute(query, variables)
            products_data = data.get("products", {})
            nodes = products_data.get("nodes", [])
            page_info = products_data.get("pageInfo", {})

            for node in nodes:
                all_products.append(node)

            cursor = page_info.get("endCursor")
            has_next = page_info.get("hasNextPage", False)

    finally:
        client.close()

    # Filter by search query (client-side on title)
    if search:
        search_lower = search.lower()
        all_products = [p for p in all_products if search_lower in p.get("title", "").lower()]

    # Paginate
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    page_products = all_products[start_idx:end_idx]

    # Add source labels from ProductSource
    product_gids = [p["id"] for p in page_products]
    sources = {ps.product_gid: ps for ps in ProductSource.objects.filter(shop=shop, product_gid__in=product_gids)}

    products_with_labels = []
    for p in page_products:
        ps = sources.get(p["id"])
        products_with_labels.append(
            {
                "id": p["id"],
                "title": p.get("title", ""),
                "handle": p.get("handle", ""),
                "vendor": p.get("vendor", ""),
                "status": p.get("status", ""),
                "featured_media": p.get("featuredMedia", {}),
                "source": ps.source if ps else "unknown_app",
                "created_by_mosaiq": ps.created_by_mosaiq if ps else False,
                "source_label": _source_label(ps.source if ps else "unknown_app"),
            }
        )

    total_pages = (len(all_products) + PAGE_SIZE - 1) // PAGE_SIZE

    return {
        "products": products_with_labels,
        "page": page,
        "has_next": end_idx < len(all_products),
        "total_pages": total_pages,
    }


def _source_label(source: str) -> str:
    """Get human-readable source label."""
    labels = {
        "manual": "Mosaiq",
        "dsers": "DSers",
        "cj": "CJ Dropshipping",
        "zendrop": "Zendrop",
        "autods": "AutoDS",
        "printify": "Printify",
        "printful": "Printful",
        "unknown_app": "Unknown",
    }
    return labels.get(source, source)
