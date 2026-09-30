"""Design tokens — build tokens dict from BrandKit and sync to app metafield.

See docs/04-extensions.md §1 (mq-tokens), F05 criterion 5.
Writes design_tokens to the app installation metafield.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from .fonts import get_font_css
from .presets import get_preset

if TYPE_CHECKING:
    from apps.core.models import Shop

    from .models import BrandKit

logger = logging.getLogger(__name__)

TOKENS_METAFIELD_NAMESPACE = "$app:mosaiq"
TOKENS_METAFIELD_KEY = "design_tokens"
TOKENS_METAFIELD_TYPE = "json"


def build_design_tokens(brandkit: BrandKit) -> dict[str, Any]:
    """Build the design_tokens dict from a BrandKit instance.

    Returns the JSON structure that goes into the mq-tokens embed.
    """
    palette = brandkit.palette or {}
    preset = get_preset(brandkit.style_preset)

    tokens: dict[str, Any] = {
        "brand_name": brandkit.brand_name,
        "tone": brandkit.tone,
        "palette": {
            "primary": palette.get("primary", "#000000"),
            "secondary": palette.get("secondary", "#666666"),
            "accent": palette.get("accent", "#FF6B35"),
            "background": palette.get("background", "#FFFFFF"),
            "text": palette.get("text", "#1A1A1A"),
        },
        "fonts": {
            "heading": get_font_css(brandkit.font_heading),
            "body": get_font_css(brandkit.font_body),
        },
        "style_preset": brandkit.style_preset,
        "radius": preset["radius"],
        "spacing": preset["spacing"],
        "button": preset["button"],
        "heading": preset["heading"],
        "version": 1,
    }

    return tokens


def sync_tokens_to_metafield(
    shop: Shop,
    access_token: str,
    brandkit: BrandKit,
) -> bool:
    """Write design_tokens to the app installation metafield.

    Sets tokens_synced_at on success.
    Returns True on success.
    """
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query

    tokens = build_design_tokens(brandkit)
    tokens_json = _json_dumps(tokens)

    client = ShopifyGraphQLClient(shop.domain, access_token, settings_api_version())
    try:
        query = load_query("metafields_set")
        metafields_input = [
            {
                "ownerId": shop.shopify_gid,
                "namespace": TOKENS_METAFIELD_NAMESPACE,
                "key": TOKENS_METAFIELD_KEY,
                "value": tokens_json,
                "type": TOKENS_METAFIELD_TYPE,
            }
        ]
        data = client.execute(query, {"metafields": metafields_input})
    finally:
        client.close()

    user_errors = data.get("metafieldsSet", {}).get("userErrors", [])
    if user_errors:
        logger.error("metafieldsSet userErrors: %s", user_errors)
        return False

    # Update tokens_synced_at
    brandkit.tokens_synced_at = timezone.now()
    brandkit.save(update_fields=["tokens_synced_at", "updated_at"])

    logger.info("Synced design tokens for %s", shop.domain)
    return True


def _json_dumps(obj: Any) -> str:
    """JSON dump with Decimal support."""
    import json
    from decimal import Decimal

    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError(f"Type {type(o)} not serializable")

    return json.dumps(obj, default=default, separators=(",", ":"))


def settings_api_version() -> str:
    from django.conf import settings

    return settings.SHOPIFY_API_VERSION
