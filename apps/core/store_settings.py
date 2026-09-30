"""Store settings — warranty policy, shipping cutoff, AI label, stock threshold.

See docs/09-ui-screens.md, docs/02-data-model.md (Shop), docs/03-shopify-integration.md §5.2.
Saving also writes the app-data metafield `settings`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import transaction

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

# Stock threshold max (07 §3)
STOCK_THRESHOLD_MAX = 10

# Valid shipping cutoff days
VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


@dataclass
class StoreSettings:
    """Store settings data."""

    guarantee_policy: str = ""
    ship_cutoff: dict[str, Any] | None = None
    ai_label_default: bool = True
    stock_threshold: int = 5

    @classmethod
    def from_shop(cls, shop: Shop) -> StoreSettings:
        """Load settings from a Shop instance."""
        return cls(
            guarantee_policy=shop.guarantee_policy,
            ship_cutoff=shop.ship_cutoff,
            ai_label_default=shop.ai_label_default,
            stock_threshold=shop.stock_threshold,
        )

    def to_metafield_value(self) -> dict[str, Any]:
        """Convert to app-data metafield value (03 §5.2)."""
        return {
            "guarantee_policy": self.guarantee_policy,
            "ship_cutoff": self.ship_cutoff,
            "ai_label_default": self.ai_label_default,
            "stock_threshold": self.stock_threshold,
        }


def validate_settings(
    guarantee_policy: str,
    ship_cutoff: dict[str, Any] | None,
    ai_label_default: bool,
    stock_threshold: int,
) -> list[str]:
    """Validate store settings. Returns list of error messages."""
    errors = []

    # Stock threshold: max 10 (07 §3)
    if stock_threshold > STOCK_THRESHOLD_MAX:
        errors.append(f"stock_threshold must be at most {STOCK_THRESHOLD_MAX}")
    if stock_threshold < 0:
        errors.append("stock_threshold must be non-negative")

    # Ship cutoff validation
    if ship_cutoff is not None:
        if not isinstance(ship_cutoff, dict):
            errors.append("ship_cutoff must be a dict")
        else:
            time_val = ship_cutoff.get("time")
            if time_val and not isinstance(time_val, str):
                errors.append("ship_cutoff.time must be a string")

            days = ship_cutoff.get("days", [])
            if isinstance(days, list):
                invalid_days = [d for d in days if d not in VALID_DAYS]
                if invalid_days:
                    errors.append(f"ship_cutoff.days contains invalid values: {invalid_days}")

            delivery_days = ship_cutoff.get("delivery_days")
            if delivery_days is not None and (not isinstance(delivery_days, int) or delivery_days < 0):
                errors.append("ship_cutoff.delivery_days must be a non-negative integer")

    return errors


def save_settings(
    shop: Shop,
    guarantee_policy: str,
    ship_cutoff: dict[str, Any] | None,
    ai_label_default: bool,
    stock_threshold: int,
) -> list[str]:
    """Save store settings to Shop and sync to app-data metafield.

    Returns list of validation errors (empty = success).
    """
    errors = validate_settings(guarantee_policy, ship_cutoff, ai_label_default, stock_threshold)
    if errors:
        return errors

    with transaction.atomic():
        shop.guarantee_policy = guarantee_policy
        shop.ship_cutoff = ship_cutoff
        shop.ai_label_default = ai_label_default
        shop.stock_threshold = stock_threshold
        shop.save(update_fields=["guarantee_policy", "ship_cutoff", "ai_label_default", "stock_threshold"])

        # Sync to app-data metafield
        _sync_settings_metafield(shop)

    return []


def _sync_settings_metafield(shop: Shop) -> None:
    """Write settings to app-data metafield `settings` (03 §5.2)."""
    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient

    settings = StoreSettings.from_shop(shop)
    metafield_value = settings.to_metafield_value()

    mutation = """
    mutation updateAppDataMetafield($input: MetafieldsSetInput!) {
        metafieldsSet(input: $input) {
            metafields {
                id
                key
            }
            userErrors {
                field
                message
            }
        }
    }
    """

    variables = {
        "input": {
            "ownerId": shop.shopify_gid,
            "namespace": "$app:mosaiq",
            "key": "settings",
            "type": "json",
            "value": _json_dumps(metafield_value),
        }
    }

    try:
        client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), "2026-07")
        result = client.execute(mutation, variables)
        user_errors = result.get("data", {}).get("metafieldsSet", {}).get("userErrors", [])
        if user_errors:
            logger.warning("Failed to sync settings metafield for %s: %s", shop.domain, user_errors)
    except Exception:
        logger.exception("Error syncing settings metafield for %s", shop.domain)


def _json_dumps(data: Any) -> str:
    """JSON serialize for metafield value."""
    import json

    return json.dumps(data, ensure_ascii=False)
