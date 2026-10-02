"""Load GPSR data from the product metafield (T-161, 07 §5).

The merchant fills the GPSR form (apps.compliance.views.gpsr_form); the
value lives in `$app:mosaiq.gpsr` on the product — the same metafield the
`mq-gpsr` theme block renders. Publish (05 §4.6) and go-live read it here
instead of the empty GpsrInfo placeholders.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings

from apps.compliance.gpsr import GpsrInfo
from apps.core.crypto import decrypt_token
from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

GPSR_NAMESPACE = "$app:mosaiq"
GPSR_KEY = "gpsr"


def load_gpsr_info(client: Any, product_gid: str) -> GpsrInfo:
    """Read `$app:mosaiq.gpsr` from a product; empty GpsrInfo when absent.

    Any API failure degrades to an empty GpsrInfo — the publish gate then
    blocks (safe default per 07 §5), never the other way around.
    """
    if not product_gid:
        return GpsrInfo()
    try:
        data = client.execute(load_query("product_metafield_get"), variables={"id": product_gid})
        product = data.get("product") or {}
        metafield = product.get("metafield")
        if not metafield or not metafield.get("value"):
            return GpsrInfo()
        return GpsrInfo.from_metafield(json.loads(metafield["value"]))
    except Exception as exc:  # noqa: BLE001 — safe default, logged
        logger.warning("GPSR metafield read failed for %s: %s", product_gid, exc)
        return GpsrInfo()


def gpsr_metafield_input(product_gid: str, info: GpsrInfo) -> dict[str, Any]:
    """Build the metafieldsSet input for one product's GPSR value."""
    return {
        "ownerId": product_gid,
        "namespace": GPSR_NAMESPACE,
        "key": GPSR_KEY,
        "type": "json",
        "value": json.dumps(info.to_metafield(), ensure_ascii=False),
    }


def sync_gpsr_metafield(
    shop: Shop, product_gid: str, info: GpsrInfo, client=None
) -> list[dict]:
    """Write GPSR to the product metafield; returns Shopify userErrors."""
    from apps.core.shopify_client import load_query as _lq

    if client is None:
        client = _client_for(shop)
    data = client.execute(_lq("metafields_set"), {"metafields": [gpsr_metafield_input(product_gid, info)]})
    return (data.get("metafieldsSet") or {}).get("userErrors") or []


def _client_for(shop: Shop):
    return ShopifyGraphQLClient(
        shop.domain,
        decrypt_token(shop.access_token_encrypted),
        settings.SHOPIFY_API_VERSION,
    )
