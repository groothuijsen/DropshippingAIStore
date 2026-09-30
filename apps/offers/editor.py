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
    from .models import OfferStatus

    if offer.status == OfferStatus.ACTIVE:
        return True, "Already active"

    # Check limits
    allowed, msg = check_activation_limits(offer.shop)
    if not allowed:
        return False, msg

    # TODO: GraphQL calls to Shopify (discountCreate, metaobjectUpsert, metafieldSet)
    # Real implementation will be verified against dev store per AGENTS.md §5
    # For now, set status and store placeholder GIDs

    offer.status = OfferStatus.ACTIVE
    offer.discount_gid = f"gid://shopify/DiscountAutomaticNode/pending-{offer.id}"
    offer.offer_display_metaobject_gid = f"gid://shopify/Metaobject/pending-{offer.id}"
    offer.save(update_fields=["status", "discount_gid", "offer_display_metaobject_gid"])

    logger.info("Offer %s activated", offer.id)
    return True, "Offer activated"


def deactivate_offer(offer: Offer) -> tuple[bool, str]:
    """Deactivate an offer (F09 criterion 7).

    Deletes discount, metaobject and metafield (idempotent).

    Returns (success, message).
    """
    from .models import OfferStatus

    if offer.status == OfferStatus.DRAFT:
        return True, "Already draft"

    # TODO: GraphQL calls to Shopify (discountDelete, metaobjectDelete, metafieldDelete)
    # For now, clear GIDs and set status

    offer.status = OfferStatus.DRAFT
    offer.discount_gid = ""
    offer.offer_display_metaobject_gid = ""
    offer.product_metafield_gid = ""
    offer.save(update_fields=["status", "discount_gid", "offer_display_metaobject_gid", "product_metafield_gid"])

    logger.info("Offer %s deactivated", offer.id)
    return True, "Offer deactivated"


def expire_offer(offer: Offer) -> None:
    """Mark an expired offer as ended (F09 criterion 5).

    Called by beat task when ends_at has passed.
    """
    from .models import OfferStatus

    if offer.is_expired and offer.status == OfferStatus.ACTIVE:
        offer.status = OfferStatus.ENDED
        offer.save(update_fields=["status"])
        logger.info("Offer %s expired", offer.id)
