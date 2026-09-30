"""Cart config — merged app-data metafield for mq-cart-drawer.

See docs/04-extensions.md §4 (cart_upsell / reward_bar → merged into
app-data metafield `cart`, 03 §5.2). No discount — the embed reads
upsell_handles via all_products[handle] (max 3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

# Max upsell products (04 §4)
MAX_UPSELL_PRODUCTS = 3
MAX_REWARD_THRESHOLDS = 3


def build_cart_config(shop: Shop) -> dict[str, Any]:
    """Build the merged cart config metafield for a shop.

    Collects all active cart_upsell and reward_bar offers and merges
    them into one config dict for the $app:mosaiq cart metafield.
    """
    from .models import Offer, OfferStatus

    active_offers = Offer.objects.filter(shop=shop, status=OfferStatus.ACTIVE)

    upsell_handles: list[str] = []
    reward_thresholds: list[dict[str, Any]] = []
    reward_labels: dict[str, str] = {}

    for offer in active_offers:
        config = offer.config or {}

        if offer.kind == "cart_upsell":
            gids = config.get("cart_upsell", {}).get("upsell_product_gids", [])
            for gid in gids[:MAX_UPSELL_PRODUCTS]:
                if gid not in upsell_handles:
                    upsell_handles.append(gid)

        elif offer.kind == "reward_bar":
            thresholds = config.get("reward_bar", {}).get("thresholds", [])
            labels = config.get("labels", {})
            for threshold in thresholds[:MAX_REWARD_THRESHOLDS]:
                reward_thresholds.append(threshold)
            # Merge labels (nl/en/de)
            for lang, label in labels.items():
                if lang in ("nl", "en", "de"):
                    reward_labels[lang] = label

    return {
        "upsell_handles": upsell_handles[:MAX_UPSELL_PRODUCTS],
        "reward_thresholds": reward_thresholds[:MAX_REWARD_THRESHOLDS],
        "reward_labels": reward_labels,
    }


def validate_cart_config(config: dict[str, Any]) -> tuple[bool, str]:
    """Validate a cart config before writing to Shopify.

    Returns (valid, message).
    """
    upsells = config.get("upsell_handles", [])
    if len(upsells) > MAX_UPSELL_PRODUCTS:
        return False, f"Too many upsell products (max {MAX_UPSELL_PRODUCTS})"

    thresholds = config.get("reward_thresholds", [])
    if len(thresholds) > MAX_REWARD_THRESHOLDS:
        return False, f"Too many reward thresholds (max {MAX_REWARD_THRESHOLDS})"

    return True, ""
