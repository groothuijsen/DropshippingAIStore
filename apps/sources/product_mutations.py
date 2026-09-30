"""Product mutations with ownership guards.

See docs/06-dropship-integrations.md §3.

Every function calls assert_writable() BEFORE any HTTP call.
If a field is locked, LockedFieldError is raised and no Shopify API call happens.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.core.shopify_client import ShopifyGraphQLClient, load_query
from apps.sources.guards import assert_writable

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)


def _get_client(shop: Shop, access_token: str) -> ShopifyGraphQLClient:
    from django.conf import settings

    return ShopifyGraphQLClient(shop.domain, access_token, settings.SHOPIFY_API_VERSION)


def product_update(
    shop: Shop,
    access_token: str,
    product_gid: str,
    *,
    title: str | None = None,
    description_html: str | None = None,
    vendor: str | None = None,
    product_type: str | None = None,
    tags: list[str] | None = None,
    template_suffix: str | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
) -> dict[str, Any]:
    """Update product fields with ownership guard.

    Raises LockedFieldError if any requested field is locked.
    No HTTP call is made if the guard fails.
    """
    # Build the set of fields being written
    fields_to_check: set[str] = set()
    if title is not None:
        fields_to_check.add("title")
    if description_html is not None:
        fields_to_check.add("descriptionHtml")
    if vendor is not None:
        fields_to_check.add("vendor")
    if product_type is not None:
        fields_to_check.add("productType")
    if tags is not None:
        fields_to_check.add("tags")
    if template_suffix is not None:
        fields_to_check.add("templateSuffix")
    if seo_title is not None:
        fields_to_check.add("seoTitle")
    if seo_description is not None:
        fields_to_check.add("seoDescription")

    # Guard check — raises LockedFieldError if any field is locked
    assert_writable(shop, product_gid, fields_to_check)

    # Build the product input
    product_input: dict[str, Any] = {"id": product_gid}
    if title is not None:
        product_input["title"] = title
    if description_html is not None:
        product_input["descriptionHtml"] = description_html
    if vendor is not None:
        product_input["vendor"] = vendor
    if product_type is not None:
        product_input["productType"] = product_type
    if tags is not None:
        product_input["tags"] = tags
    if template_suffix is not None:
        product_input["templateSuffix"] = template_suffix
    if seo_title is not None or seo_description is not None:
        seo: dict[str, str] = {}
        if seo_title is not None:
            seo["title"] = seo_title
        if seo_description is not None:
            seo["description"] = seo_description
        product_input["seo"] = seo

    client = _get_client(shop, access_token)
    try:
        query = load_query("product_update")
        data = client.execute(query, {"input": product_input})
    finally:
        client.close()

    user_errors = data.get("productSet", {}).get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"productUpdate userErrors: {user_errors}")

    return data.get("productSet", {}).get("product", {})


def product_set_template_suffix(
    shop: Shop,
    access_token: str,
    product_gid: str,
    template_suffix: str,
) -> dict[str, Any]:
    """Set templateSuffix on a product.

    This is the ONLY product field Mosaiq may write on sourced products (06 §3).
    """
    # templateSuffix is always writable
    assert_writable(shop, product_gid, {"templateSuffix"})

    client = _get_client(shop, access_token)
    try:
        query = load_query("product_update")
        data = client.execute(query, {"input": {"id": product_gid, "templateSuffix": template_suffix}})
    finally:
        client.close()

    user_errors = data.get("productSet", {}).get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"productSet userErrors: {user_errors}")

    return data.get("productSet", {}).get("product", {})


def product_set_metafield(
    shop: Shop,
    access_token: str,
    product_gid: str,
    *,
    namespace: str = "$app:mosaiq",
    key: str,
    value: str,
    type_name: str = "json",
) -> dict[str, Any]:
    """Set a metafield on a product.

    Metafields in the $app:mosaiq namespace are always writable (06 §3).
    """
    # Mosaiq metafields are always writable
    assert_writable(shop, product_gid, {f"{namespace}.{key}"})

    from apps.core.shopify_client import load_query as _load

    metafields_input = [
        {
            "ownerId": product_gid,
            "namespace": namespace,
            "key": key,
            "value": value,
            "type": type_name,
        }
    ]

    client = _get_client(shop, access_token)
    try:
        query = _load("metafields_set")
        data = client.execute(query, {"metafields": metafields_input})
    finally:
        client.close()

    user_errors = data.get("metafieldsSet", {}).get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"metafieldsSet userErrors: {user_errors}")

    return data.get("metafieldsSet", {}).get("metafields", [])


def product_delete(
    shop: Shop,
    access_token: str,
    product_gid: str,
) -> bool:
    """Delete a product. Only allowed if Mosaiq created it."""
    from apps.sources.models import ProductSource

    ps = ProductSource.objects.filter(shop=shop, product_gid=product_gid).first()
    if ps and not ps.created_by_mosaiq:
        from apps.sources.guards import LockedFieldError

        raise LockedFieldError(["__delete__"], product_gid)

    query_str = """
    mutation ProductDelete($input: ProductSetInput!) {
      productSet(input: $input) {
        product { id }
        userErrors { field message code }
      }
    }
    """
    client = _get_client(shop, access_token)
    try:
        data = client.execute(query_str, {"input": {"id": product_gid}})
    finally:
        client.close()

    user_errors = data.get("productSet", {}).get("userErrors", [])
    if user_errors:
        raise RuntimeError(f"productDelete userErrors: {user_errors}")

    return True
