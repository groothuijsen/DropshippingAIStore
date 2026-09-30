"""Omnibus compliance — prior price calculation.

See docs/07-compliance.md §1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from apps.compliance.models import PriceHistory
    from apps.core.models import Shop

logger = logging.getLogger(__name__)


@dataclass
class PriorPrice:
    amount: Decimal
    currency: str


@dataclass
class Reduction:
    prior: Decimal
    current: Decimal
    percent: int


def prior_price(
    shop: Shop,
    variant_gid: str,
    current: Decimal,
    market: str = "primary",
    now: object | None = None,
) -> PriorPrice | None:
    """Calculate the prior price for Omnibus compliance (07 §1.2).

    The prior price is the lowest price in the 30-day window before the
    current price reduction started.

    Returns None if insufficient history or no reduction.
    """
    from apps.compliance.models import PriceAttestation, PriceHistory

    now = now or timezone.now()
    rows: list[PriceHistory] = list(
        PriceHistory.objects.filter(
            shop=shop,
            variant_gid=variant_gid,
            market_handle=market,
            observed_at__lte=now,
        ).order_by("observed_at")
    )
    if not rows:
        return None

    # 1. Find the start time of the current price
    i = len(rows) - 1
    while i > 0 and rows[i - 1].price == current:
        i -= 1
    reduction_start = rows[i].observed_at
    window_start = reduction_start - timedelta(days=30)

    # 2. Get observations before the reduction started
    before = [r for r in rows if r.observed_at < reduction_start]

    # 3. Find the anchor: last observation at or before window_start
    anchor = next(
        (r for r in reversed(before) if r.observed_at <= window_start),
        None,
    )

    # 4. Prices within the window
    in_window = [r.price for r in before if r.observed_at > window_start]
    candidates = in_window + ([anchor.price] if anchor else [])

    if anchor is None:
        # History doesn't fully cover the window — check attestation
        att = PriceAttestation.objects.filter(
            shop=shop,
            variant_gid=variant_gid,
            valid_until__gt=now,
        ).first()
        if att is None:
            return None  # Insufficient history, do NOT show a reduction
        candidates.append(att.lowest_price_30d)

    if not candidates:
        return None

    return PriorPrice(amount=min(candidates), currency=rows[-1].currency)


def reduction(current: Decimal, prior: Decimal) -> Reduction | None:
    """Calculate the reduction percentage.

    Returns None if current >= prior (not a real reduction).
    Percentages always round DOWN (07 §1.3).
    """
    import math

    if current >= prior:
        return None

    pct = int(math.floor((prior - current) / prior * 100))
    return Reduction(prior=prior, current=current, percent=pct)
