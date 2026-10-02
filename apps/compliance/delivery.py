"""Delivery estimate logic (12 §2.4, F18-3)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models import Shop


@dataclass
class DeliveryEstimate:
    min_days: int
    max_days: int
    ship_from: str
    source: str  # "profile" | "override"
    shipping_cost: Decimal | None = None
    free_from: Decimal | None = None
    over_30_days: bool = False


def estimate(shop: Shop, product_gid: str, market: str) -> DeliveryEstimate | None:
    """Return the delivery estimate for a product in a market.

    min_days = processing_min + transit_min
    max_days = processing_max + transit_max

    Returns None if no profile or override applies.
    """
    from apps.compliance.models import DeliveryOverride, DeliveryProfile
    from apps.sources.models import ProductSource

    # Find the product's source to locate the right profile
    source_row = ProductSource.objects.filter(shop=shop, product_gid=product_gid).first()
    source_app = source_row.source if source_row else None

    # Check override first (higher priority)
    override = DeliveryOverride.objects.filter(shop=shop, product_gid=product_gid).first()
    profile = (
        DeliveryProfile.objects.filter(shop=shop, source_app=source_app).first()
        if source_app
        else None
    )

    # Determine processing days (override > profile > None)
    proc_min: int | None = None
    proc_max: int | None = None
    ship_from: str | None = None
    source: str | None = None
    ship_cost: Decimal | None = None
    free_from: Decimal | None = None

    # Profile provides defaults
    if profile is not None:
        proc_min = profile.processing_days_min
        proc_max = profile.processing_days_max
        ship_from = profile.ship_from_country
        source = "profile"
        if profile.shipping_cost and market in profile.shipping_cost:
            mkt = profile.shipping_cost[market]
            ship_cost = Decimal(mkt.get("amount", "0"))
            free_from = Decimal(mkt["free_from"]) if mkt.get("free_from") else None

    # Override can replace any field
    if override is not None:
        if override.processing_days_min is not None:
            proc_min = override.processing_days_min
        if override.processing_days_max is not None:
            proc_max = override.processing_days_max
        if override.ship_from_country:
            ship_from = override.ship_from_country
        if override.shipping_cost and market in override.shipping_cost:
            mkt = override.shipping_cost[market]
            ship_cost = Decimal(mkt.get("amount", "0"))
            free_from = Decimal(mkt["free_from"]) if mkt.get("free_from") else None
        source = "override"

    # Determine transit days (override > profile > None)
    transit_min: int | None = None
    transit_max: int | None = None

    if profile is not None and profile.transit_days and market in profile.transit_days:
        rng = profile.transit_days[market]
        if isinstance(rng, list) and len(rng) == 2:
            transit_min, transit_max = rng

    if override is not None and override.transit_days and market in override.transit_days:
        rng = override.transit_days[market]
        if isinstance(rng, list) and len(rng) == 2:
            transit_min, transit_max = rng

    # All required fields must be present
    if proc_min is None or proc_max is None or transit_min is None or transit_max is None:
        return None
    if ship_from is None or source is None:
        return None

    min_days = proc_min + transit_min
    max_days = proc_max + transit_max

    return DeliveryEstimate(
        min_days=min_days,
        max_days=max_days,
        ship_from=ship_from,
        source=source,
        shipping_cost=ship_cost,
        free_from=free_from,
        over_30_days=max_days > 30,
    )
