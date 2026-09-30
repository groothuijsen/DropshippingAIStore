"""Omnibus pricing — prior_price() and reduction() per 07 §1.

See docs/07-compliance.md §1.2.
Prior price = lowest price in window [reduction_start − 30 days, reduction_start).
Reduction = (prior − current) / prior × 100, rounded DOWN.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from django.utils import timezone

from .models import PriceAttestation, PriceHistory

logger = logging.getLogger(__name__)

# Window: 30 days before reduction start (07 §1.1)
PRICE_WINDOW_DAYS = 30


@dataclass
class PriorPrice:
    """Result of prior_price calculation."""

    amount: Decimal
    currency: str


@dataclass
class Reduction:
    """Result of reduction calculation."""

    prior: Decimal
    current: Decimal
    percent: int


def prior_price(
    shop: Any,
    variant_gid: str,
    current: Decimal,
    market: str = "primary",
    now: Any = None,
) -> PriorPrice | None:
    """Calculate the prior price for Omnibus compliance.

    See docs/07-compliance.md §1.2 for the algorithm.

    Args:
        shop: Shop instance
        variant_gid: Shopify variant GID
        current: Current price
        market: Market handle (default "primary")
        now: Current time (default timezone.now())

    Returns:
        PriorPrice or None if insufficient history
    """
    if now is None:
        now = timezone.now()

    rows = list(
        PriceHistory.objects.filter(
            shop=shop,
            variant_gid=variant_gid,
            market_handle=market,
            observed_at__lte=now,
        ).order_by("observed_at")
    )

    if not rows:
        return None

    # 1. Find reduction start time
    # Start from the end, go back while price == current
    i = len(rows) - 1
    while i > 0 and rows[i - 1].price == current:
        i -= 1
    reduction_start = rows[i].observed_at
    window_start = reduction_start - timedelta(days=PRICE_WINDOW_DAYS)

    # 2. Find prices before reduction start
    before = [r for r in rows if r.observed_at < reduction_start]

    # 3. Anchor: last observation at or before window_start
    anchor = next((r for r in reversed(before) if r.observed_at <= window_start), None)

    # 4. In-window prices: observations after window_start
    in_window = [r.price for r in before if r.observed_at > window_start]

    # 5. Candidates
    candidates = in_window + ([anchor.price] if anchor else [])

    # 6. If no anchor, check attestation
    if anchor is None:
        att = PriceAttestation.objects.filter(
            shop=shop,
            variant_gid=variant_gid,
            valid_until__gt=now,
        ).first()
        if att is None:
            return None  # insufficient history → do NOT show a reduction
        candidates.append(att.lowest_price_30d)

    if not candidates:
        return None

    return PriorPrice(amount=min(candidates), currency=rows[-1].currency)


def reduction(current: Decimal, prior: Decimal) -> Reduction | None:
    """Calculate reduction percentage.

    See docs/07-compliance.md §1.2.
    Returns None if current >= prior (not a real reduction).
    Percent is rounded DOWN (ROUND_FLOOR).
    """
    if current >= prior:
        return None  # not a real reduction → show nothing

    pct = ((prior - current) / prior * 100).to_integral_value(rounding=ROUND_FLOOR)
    return Reduction(prior=prior, current=current, percent=int(pct))


def is_reduction_available(
    shop: Any,
    variant_gid: str,
    current: Decimal,
    market: str = "primary",
    now: Any = None,
) -> bool:
    """Check if a reduction is available (prior_price exists and is lower)."""
    prior = prior_price(shop, variant_gid, current, market, now)
    if prior is None:
        return False
    return current < prior.amount
