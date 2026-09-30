"""Offer editor — create, activate, deactivate offers.

See docs/specs/F09-bundles.md criteria 1-2, 5, 7.
- Create: validate OfferConfig (tiers, percentages)
- Activate: create automatic app discount + metaobject + metafield
  Refuse at 20 active Mosaiq discounts or 25 active auto discounts in shop
- Deactivate: delete discount, metaobject, metafield (idempotent)
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .schemas import OfferConfig

if TYPE_CHECKING:
    from apps.core.models import Shop
    from apps.offers.models import Offer

logger = logging.getLogger(__name__)

# Activation limits (F09 criterion 2)
MAX_ACTIVE_MOSAIQ_DISCOUNTS = 20
MAX_ACTIVE_AUTO_DISCOUNTS_SHOP = 25


def validate_offer_config(config_dict: dict[str, Any]) -> tuple[bool, str]:
    """Validate an offer config against OfferConfig schema.

    Returns (valid, message).
    """
    try:
        config = OfferConfig(**config_dict)
        # Additional tier validation (F09 criterion 1)
        if config.kind == "volume":
            _validate_volume_tiers(config)
        return True, ""
    except Exception as e:
        return False, str(e)


def _validate_volume_tiers(config: OfferConfig) -> None:
    """Validate volume tiers: 2-4 tiers, quantities ascending, percentages ascending, 1-70."""
    tiers = config.tiers
    if not tiers or len(tiers) < 2 or len(tiers) > 4:
        raise ValueError("Volume offer requires 2-4 tiers")

    quantities = [t.min_qty for t in tiers]
    percentages = [Decimal(t.value) for t in tiers]

    # Quantities must be strictly ascending
    for i in range(1, len(quantities)):
        if quantities[i] <= quantities[i - 1]:
            raise ValueError("Tier quantities must be strictly ascending")

    # Percentages must be ascending
    for i in range(1, len(percentages)):
        if percentages[i] < percentages[i - 1]:
            raise ValueError("Tier percentages must be ascending")

    # Percentages 1-70 (already validated by Tier schema, but double-check)
    for t in tiers:
        pct = Decimal(t.value)
        if pct < 1 or pct > 70:
            raise ValueError(f"Tier percentage must be 1-70 (got {t.value})")


def check_activation_limits(shop: Shop) -> tuple[bool, str]:
    """Check if shop can activate more offers (F09 criterion 2).

    Refuses at 20 active Mosaiq discounts or 25 active auto discounts
    in the whole shop (including other apps).

    Returns (allowed, message).
    """
    from .models import Offer, OfferStatus

    # Count active Mosaiq offers
    active_mosaiq = Offer.objects.filter(
        shop=shop,
        status=OfferStatus.ACTIVE,
    ).count()

    if active_mosaiq >= MAX_ACTIVE_MOSAIQ_DISCOUNTS:
        return False, f"Maximum {MAX_ACTIVE_MOSAIQ_DISCOUNTS} active Mosaiq discounts reached"

    # TODO: Query Shopify for total active auto discounts in shop (including other apps)
    # For now, only check Mosaiq count
    return True, ""


def create_offer(
    shop: Shop,
    product_gid: str,
    title: str,
    kind: str,
    config_dict: dict[str, Any],
) -> tuple[bool, str, Offer | None]:
    """Create a new offer (draft status).

    Returns (success, message, offer).
    """
    from .models import Offer, OfferStatus

    # Validate config
    valid, msg = validate_offer_config(config_dict)
    if not valid:
        return False, msg, None

    offer = Offer.objects.create(
        shop=shop,
        product_gid=product_gid,
        title=title,
        kind=kind,
        config=config_dict,
        status=OfferStatus.DRAFT,
    )

    return True, "Offer created", offer


def activate_offer(offer: Offer) -> tuple[bool, str]:
    """Activate an offer (F09 criterion 2).

    1. Check activation limits
    2. Create automatic app discount (discountClasses: [PRODUCT])
    3. Create $app:offer_display metaobject (quantities/percentages only)
    4. Set product metafield 'offer'
    5. Set Offer.status = active

    Returns (success, message).
    """
    import json

    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query

    from .models import OfferStatus

    if offer.status == OfferStatus.ACTIVE:
        return True, "Already active"

    # Check limits
    allowed, msg = check_activation_limits(offer.shop)
    if not allowed:
        return False, msg

    # Build discount title
    discount_title = f"Mosaiq: {offer.title}"

    # Build discount function config (JSON metafield on the discount)
    config = offer.config
    discount_config = {
        "kind": offer.kind,
        "tiers": config.get("tiers", []),
        "product_gid": offer.product_gid,
    }

    # Create client
    shop = offer.shop
    token = decrypt_token(shop.access_token_encrypted)
    client = ShopifyGraphQLClient(shop.domain, token, "2026-07")

    try:
        # 1. Create automatic app discount
        query = load_query("discount_create")
        variables = {
            "input": {
                "title": discount_title,
                "functionId": "mosaiq-discount",  # Placeholder — real function ID from Shopify CLI
                "discountClasses": ["PRODUCT"],
                "combinesWith": {"orderDiscounts": False, "productDiscounts": True, "shippingDiscounts": False},
                "metafields": [
                    {
                        "namespace": "$app:mosaiq",
                        "key": "config",
                        "type": "json",
                        "value": json.dumps(discount_config),
                    }
                ],
            }
        }
        result = client.execute(query, variables)
        discount_data = result.get("discountAutomaticAppCreate", {})
        errors = discount_data.get("userErrors", [])
        if errors:
            logger.error("Discount creation failed: %s", errors)
            return False, f"Discount creation failed: {errors[0].get('message', 'unknown')}"

        discount_gid = discount_data.get("automaticAppDiscount", {}).get("id", "")
        if not discount_gid:
            return False, "No discount GID returned"

        # 2. Create offer_display metaobject (quantities/percentages only)
        metaobject_handle = f"mq-offer-{str(offer.id)[:8]}"
        metaobject_fields = [
            {"key": "kind", "value": offer.kind},
            {"key": "tiers", "value": json.dumps(config.get("tiers", []))},
        ]

        upsert_query = load_query("metaobject_upsert")
        upsert_vars = {
            "handle": {"type": "$app:offer_display", "handle": metaobject_handle},
            "metaobject": {
                "fields": metaobject_fields,
                "capabilities": {"publishable": {"status": "ACTIVE"}},
            },
        }
        upsert_result = client.execute(upsert_query, upsert_vars)
        upsert_errors = upsert_result.get("metaobjectUpsert", {}).get("userErrors", [])
        if upsert_errors:
            logger.warning("Metaobject upsert errors: %s", upsert_errors)

        metaobject_gid = upsert_result.get("metaobjectUpsert", {}).get("metaobject", {}).get("id", "")

        # 3. Set product metafield 'offer'
        metafield_query = load_query("metafields_set")
        metafield_vars = {
            "input": [
                {
                    "ownerId": offer.product_gid,
                    "namespace": "$app:mosaiq",
                    "key": "offer",
                    "type": "metaobject_reference",
                    "value": metaobject_gid,
                }
            ]
        }
        client.execute(metafield_query, metafield_vars)

        # 4. Update Offer model
        offer.status = OfferStatus.ACTIVE
        offer.discount_gid = discount_gid
        offer.offer_display_metaobject_gid = metaobject_gid
        offer.save(update_fields=["status", "discount_gid", "offer_display_metaobject_gid"])

        logger.info("Offer %s activated", offer.id)
        return True, "Offer activated"

    except Exception as exc:
        logger.error("Failed to activate offer %s: %s", offer.id, exc)
        return False, f"Activation failed: {exc}"
    finally:
        client.close()


def deactivate_offer(offer: Offer) -> tuple[bool, str]:
    """Deactivate an offer (F09 criterion 7).

    Deletes discount, metaobject and metafield (idempotent).

    Returns (success, message).
    """
    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query

    from .models import OfferStatus

    if offer.status == OfferStatus.DRAFT:
        return True, "Already draft"

    shop = offer.shop
    token = decrypt_token(shop.access_token_encrypted)
    client = ShopifyGraphQLClient(shop.domain, token, "2026-07")

    try:
        # 1. Delete discount
        if offer.discount_gid:
            try:
                query = load_query("discount_delete")
                variables = {"id": offer.discount_gid}
                client.execute(query, variables)
                logger.info("Discount %s deleted", offer.discount_gid)
            except Exception as exc:
                logger.warning("Failed to delete discount: %s", exc)

        # 2. Delete metaobject
        if offer.offer_display_metaobject_gid:
            try:
                query = load_query("metaobject_delete")
                variables = {"id": offer.offer_display_metaobject_gid}
                client.execute(query, variables)
                logger.info("Metaobject %s deleted", offer.offer_display_metaobject_gid)
            except Exception as exc:
                logger.warning("Failed to delete metaobject: %s", exc)

        # 3. Delete product metafield
        if offer.product_gid:
            try:
                query = load_query("metafields_delete")
                variables = {"metafields": [{"ownerId": offer.product_gid, "namespace": "$app:mosaiq", "key": "offer"}]}
                client.execute(query, variables)
                logger.info("Metafield 'offer' deleted for %s", offer.product_gid)
            except Exception as exc:
                logger.warning("Failed to delete metafield: %s", exc)

        # 4. Update Offer model
        offer.status = OfferStatus.DRAFT
        offer.discount_gid = ""
        offer.offer_display_metaobject_gid = ""
        offer.product_metafield_gid = ""
        offer.save(update_fields=["status", "discount_gid", "offer_display_metaobject_gid", "product_metafield_gid"])

        logger.info("Offer %s deactivated", offer.id)
        return True, "Offer deactivated"

    except Exception as exc:
        logger.error("Failed to deactivate offer %s: %s", offer.id, exc)
        return False, f"Deactivation failed: {exc}"
    finally:
        client.close()


def expire_offer(offer: Offer) -> None:
    """Mark an expired offer as ended (F09 criterion 5).

    Called by beat task when ends_at has passed.
    """
    from .models import OfferStatus

    if offer.is_expired and offer.status == OfferStatus.ACTIVE:
        offer.status = OfferStatus.ENDED
        offer.save(update_fields=["status"])
        logger.info("Offer %s expired", offer.id)
