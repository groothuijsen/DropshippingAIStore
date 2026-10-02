"""Price advisor — advise() per F17 formula.

N = (C + S + A + F) / (1 − r − m − p × (1 + v))
P = N × (1 + v)
break-even: same with m = 0
rounded: smallest price ≥ P ending in price_ending (.95, .99, .00)
actual margin at the rounded price.

All money as Decimal; rounded half-up to 2 decimals only at the end.
Denominator <= 0.05 → error "Target margin too high for these costs".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MARGIN_TOO_HIGH = "Target margin too high for these costs"

_CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass
class PricingAdvice:
    net_price: Decimal | None = None
    consumer_price: Decimal | None = None
    break_even_price: Decimal | None = None
    rounded_price: Decimal | None = None
    actual_margin: Decimal | None = None
    error: str | None = None


def _consumer_price(
    cost: Decimal,
    shipping: Decimal,
    ad_cost: Decimal,
    fee_fixed: Decimal,
    fee_pct: Decimal,
    returns_pct: Decimal,
    margin_pct: Decimal,
    vat_rate: Decimal,
) -> tuple[Decimal | None, str | None]:
    """Compute N and P; return (P, error)."""
    denominator = Decimal("1") - returns_pct - margin_pct - fee_pct * (Decimal("1") + vat_rate)
    if denominator <= Decimal("0.05"):
        return None, MARGIN_TOO_HIGH
    net = (cost + shipping + ad_cost + fee_fixed) / denominator
    return net * (Decimal("1") + vat_rate), None


def _round_price(consumer: Decimal, price_ending: int) -> Decimal:
    """Smallest price >= consumer ending in price_ending (.95/.99/.00)."""
    cents = int((consumer * 100).to_integral_value(rounding="ROUND_CEILING"))
    last_two = cents % 100
    if price_ending == 0:  # .00 endings
        if last_two != 0:
            cents = cents - last_two + 100
        return Decimal(cents) / 100
    target = cents - last_two + price_ending
    if target < cents:
        target += 100
    return Decimal(target) / 100


def _actual_margin(
    rounded: Decimal,
    cost: Decimal,
    shipping: Decimal,
    ad_cost: Decimal,
    fee_fixed: Decimal,
    fee_pct: Decimal,
    returns_pct: Decimal,
    vat_rate: Decimal,
) -> Decimal:
    net = rounded / (Decimal("1") + vat_rate)
    numerator = net - cost - shipping - ad_cost - fee_fixed - fee_pct * rounded - returns_pct * net
    return numerator / net


def advise(
    *,
    cost: Decimal,
    shipping: Decimal,
    ad_cost: Decimal,
    payment_fee_fixed: Decimal,
    payment_fee_pct: Decimal,
    returns_pct: Decimal,
    margin_pct: Decimal,
    vat_rate: Decimal,
    price_ending: int,
) -> PricingAdvice:
    """Calculate the price advice for one variant in one market (F17)."""
    advice = PricingAdvice()

    consumer, error = _consumer_price(
        cost, shipping, ad_cost, payment_fee_fixed, payment_fee_pct,
        returns_pct, margin_pct, vat_rate,
    )
    if error:
        advice.error = error
        return advice

    breakeven, _ = _consumer_price(
        cost, shipping, ad_cost, payment_fee_fixed, payment_fee_pct,
        returns_pct, Decimal("0"), vat_rate,
    )

    advice.consumer_price = _money(consumer)
    advice.net_price = _money(consumer / (Decimal("1") + vat_rate))
    if breakeven is not None:
        advice.break_even_price = _money(breakeven)
    advice.rounded_price = _money(_round_price(consumer, price_ending))
    advice.actual_margin = _actual_margin(
        advice.rounded_price, cost, shipping, ad_cost,
        payment_fee_fixed, payment_fee_pct, returns_pct, vat_rate,
    )
    return advice
