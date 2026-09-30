"""Import step — fetches products, detects source, builds ImportResult.

See docs/05-ai-pipeline.md §4.1, docs/06-dropship-integrations.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.ai.schemas import ImportResult
from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)


def _get_client(shop: Shop, access_token: str) -> ShopifyGraphQLClient:
    from django.conf import settings

    return ShopifyGraphQLClient(shop.domain, access_token, settings.SHOPIFY_API_VERSION)


def import_product_gid(
    shop: Shop,
    access_token: str,
    product_gid: str,
) -> ImportResult:
    """Import an existing Shopify product by GID.

    Fetches the product via GraphQL, detects the source, and returns
    an ImportResult with reference_image_urls from the product media.
    """
    from apps.sources.models import DetectedBy, ProductSource
    from apps.sources.rules import detect_source, get_locked_fields

    client = _get_client(shop, access_token)

    try:
        query = load_query("product_get")
        data = client.execute(query, {"id": product_gid})
    finally:
        client.close()

    product = data.get("product")
    if product is None:
        from apps.generator.errors import ImportNotFound

        raise ImportNotFound(message=f"Product {product_gid} not found")

    # Extract media URLs
    reference_image_urls: list[str] = []
    for media_node in product.get("media", {}).get("nodes", []):
        if media_node.get("image", {}).get("url"):
            reference_image_urls.append(media_node["image"]["url"])

    # Extract price from first variant
    variants = product.get("variants", {}).get("nodes", [])
    price = None
    currency = shop.currency_code
    if variants:
        try:
            from decimal import Decimal

            price = Decimal(variants[0].get("price", "0"))
        except Exception:
            pass

    # Detect source
    vendor = product.get("vendor", "")
    sku = None
    if variants:
        sku = variants[0].get("sku")

    # Check existing ProductSource
    ps = ProductSource.objects.filter(shop=shop, product_gid=product_gid).first()

    if ps is None:
        # Detect source
        onboarding_apps = shop.import_apps or []
        source, detected_by_str = detect_source(
            vendor=vendor or None,
            sku=sku or None,
            onboarding_apps=onboarding_apps,
        )

        # Map detected_by string to choices
        detected_by_map = {
            "fulfillment_location": DetectedBy.FULFILLMENT_LOCATION,
            "vendor": DetectedBy.VENDOR,
            "sku": DetectedBy.SKU,
            "onboarding": DetectedBy.ONBOARDING,
            "mosaiq": DetectedBy.MOSAIQ,
        }
        detected_by = detected_by_map.get(detected_by_str, DetectedBy.ONBOARDING)

        locked = get_locked_fields(source)

        ps = ProductSource.objects.create(
            shop=shop,
            product_gid=product_gid,
            source=source,
            detected_by=detected_by,
            created_by_mosaiq=False,
            locked_fields=locked,
        )

    # Build facts from specs (in our own words — just key-value pairs)
    specs: dict[str, str] = {}
    for metafield in product.get("metafields", {}).get("nodes", []):
        key = metafield.get("key", "")
        value = metafield.get("value", "")
        if key and value:
            specs[key] = value

    # Simple facts extraction from title and product type
    facts: list[str] = []
    title = product.get("title", "")
    product_type = product.get("productType", "")
    if title:
        facts.append(f"Product: {title}")
    if product_type:
        facts.append(f"Type: {product_type}")

    return ImportResult(
        product_gid=product_gid,
        source_app=ps.source,  # type: ignore[arg-type]
        title=title,
        facts=facts,
        specs=specs,
        reference_image_urls=reference_image_urls[:8],
        price=price,
        currency=currency,
        locked_fields=ps.locked_fields,
    )


def import_manual(
    shop: Shop,
    access_token: str,
    *,
    title: str,
    description: str,
    specs: dict[str, str] | None = None,
    price: str | None = None,
    currency: str | None = None,
) -> ImportResult:
    """Create a manual product via productSet and return an ImportResult.

    The product is created with status DRAFT, source=manual,
    created_by_mosaiq=True.
    """
    from decimal import Decimal

    from apps.sources.models import DetectedBy, ProductSource, SourceApp

    client = _get_client(shop, access_token)

    try:
        query = load_query("product_create_manual")

        # Build the productSet input
        product_input: dict[str, Any] = {
            "title": title,
            "descriptionHtml": f"<p>{description}</p>",
            "status": "DRAFT",
        }

        if price:
            product_input["variants"] = [
                {
                    "price": price,
                    "sku": f"MQ-{title[:20].upper().replace(' ', '-')}",
                }
            ]

        data = client.execute(query, {"input": product_input})
    finally:
        client.close()

    user_errors = data.get("productSet", {}).get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"productSet userErrors: {user_errors}")

    product_data = data.get("productSet", {}).get("product", {})
    product_gid = product_data.get("id", "")

    if not product_gid:
        raise RuntimeError("productSet returned no product ID")

    # Create ProductSource
    ProductSource.objects.create(
        shop=shop,
        product_gid=product_gid,
        source=SourceApp.MANUAL,
        detected_by=DetectedBy.MOSAIQ,
        created_by_mosaiq=True,
        locked_fields=[],
    )

    return ImportResult(
        product_gid=product_gid,
        source_app="manual",
        title=title,
        facts=[f"Product: {title}", f"Description: {description[:200]}"],
        specs=specs or {},
        reference_image_urls=[],
        price=Decimal(price) if price else None,
        currency=currency or shop.currency_code,
        locked_fields=[],
    )
