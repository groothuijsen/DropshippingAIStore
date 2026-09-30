"""Unit price calculation — EU Omnibus unit price requirements.

See docs/07-compliance.md §2.
Reference units: kg, l, m, m², m³. No "per 100 g" or "per 100 ml" (not permitted in DE).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Factor to convert stored unit to reference unit (07 §2.2)
UNIT_FACTORS: dict[str, Decimal] = {
    "g": Decimal("0.001"),  # ÷ 1000 → kg
    "kg": Decimal("1"),  # × 1
    "ml": Decimal("0.001"),  # ÷ 1000 → l
    "l": Decimal("1"),  # × 1
    "cm": Decimal("0.01"),  # ÷ 100 → m
    "m": Decimal("1"),  # × 1
    "m2": Decimal("1"),  # × 1
    "m3": Decimal("1"),  # × 1
}

# Reference unit label per stored unit
REFERENCE_UNIT: dict[str, str] = {
    "g": "kg",
    "kg": "kg",
    "ml": "l",
    "l": "l",
    "cm": "m",
    "m": "m",
    "m2": "m²",
    "m3": "m³",
}


def unit_price(total: Decimal, qty: int, net_quantity: Decimal, unit: str) -> Decimal:
    """Calculate unit price per reference unit.

    Args:
        total: Total price for the quantity
        qty: Number of items
        net_quantity: Net quantity per item (e.g. 30 for 30 ml)
        unit: Stored unit (g, kg, ml, l, cm, m, m2, m3)

    Returns:
        Price per reference unit, rounded to 2 decimal places (ROUND_HALF_UP)
    """
    if unit not in UNIT_FACTORS:
        raise ValueError(f"Unknown unit: {unit}")

    factor = UNIT_FACTORS[unit]
    ref_qty = net_quantity * qty * factor

    if ref_qty <= 0:
        raise ValueError("Reference quantity must be positive")

    return (total / ref_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_reference_unit(unit: str) -> str:
    """Get the reference unit label for a stored unit."""
    if unit not in REFERENCE_UNIT:
        raise ValueError(f"Unknown unit: {unit}")
    return REFERENCE_UNIT[unit]


def format_unit_price(price: Decimal, unit: str) -> str:
    """Format unit price for display: '€ 83.17 / 1 l'."""
    ref_unit = get_reference_unit(unit)
    return f"€ {price} / {ref_unit}"


def is_unit_price_required(net_quantity: Decimal | None, unit: str | None) -> bool:
    """Check if unit price is required for this variant.

    Required if sold by weight, volume, length or area (07 §2.1).
    """
    return net_quantity is not None and net_quantity > 0 and unit is not None
