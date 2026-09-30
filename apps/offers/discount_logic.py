"""Discount logic — pure reference implementation for the Discount Function.

See docs/04-extensions.md §2 (pseudo logic).
Deterministic, no network. The Shopify Function (JS/WASM) mirrors this logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .schemas import OfferConfig


@dataclass
class CartLine:
    """Simplified cart line for discount calculation."""

    id: str  # cart line id
    product_id: str  # gid://shopify/Product/...
    variant_id: str  # gid://shopify/ProductVariant/...
    quantity: int
    price_cents: int  # current unit price in cents
    attributes: dict[str, str] = field(default_factory=dict)  # e.g. _mq_gift


@dataclass
class DiscountTarget:
    """A target line in a discount candidate."""

    line_id: str
    quantity: int | None = None  # only for bogo/gift


@dataclass
class DiscountCandidate:
    """A discount candidate to return to Shopify."""

    message: str
    targets: list[DiscountTarget]
    percentage: Decimal


@dataclass
class DiscountResult:
    """Result of discount calculation."""

    candidates: list[DiscountCandidate] = field(default_factory=list)

    @property
    def has_operations(self) -> bool:
        return len(self.candidates) > 0


def _eligible_lines(config: OfferConfig, lines: list[CartLine]) -> list[CartLine]:
    """Filter cart lines to eligible products."""
    product_ids = set(config.product_ids)
    return [line for line in lines if line.product_id in product_ids]


def _discount_percentage(value: str) -> Decimal:
    """Convert string percentage to Decimal."""
    return Decimal(value)


def calculate_volume(config: OfferConfig, lines: list[CartLine]) -> DiscountResult:
    """Volume discount: highest tier with min_qty <= total qty."""
    eligible = _eligible_lines(config, lines)
    if not eligible or not config.tiers:
        return DiscountResult()

    total_qty = sum(line.quantity for line in eligible)

    # Find highest tier with min_qty <= qty
    applicable = [t for t in config.tiers if t.min_qty <= total_qty]
    if not applicable:
        return DiscountResult()

    tier = max(applicable, key=lambda t: t.min_qty)
    pct = _discount_percentage(tier.value)

    targets = [DiscountTarget(line_id=line.id) for line in eligible]
    message = config.labels.nl  # primary language label

    return DiscountResult(
        candidates=[
            DiscountCandidate(
                message=message,
                targets=targets,
                percentage=pct,
            )
        ]
    )


def calculate_bogo(config: OfferConfig, lines: list[CartLine]) -> DiscountResult:
    """BOGO: expand to units, sort by price ascending, discount cheapest free units."""
    eligible = _eligible_lines(config, lines)
    if not eligible or not config.bogo:
        return DiscountResult()

    buy_qty = config.bogo.buy_qty
    get_qty = config.bogo.get_qty
    group = buy_qty + get_qty
    get_pct = _discount_percentage(config.bogo.get_percentage)

    # Expand lines into single units, sorted by price ascending
    units: list[tuple[CartLine, int]] = []  # (line, unit_index)
    for line in eligible:
        for i in range(line.quantity):
            units.append((line, i))
    units.sort(key=lambda x: x[0].price_cents)

    # Number of free units
    free_units = (len(units) // group) * get_qty
    if free_units == 0:
        return DiscountResult()

    # Discount on the cheapest free_units units
    discounted: dict[str, int] = {}  # line_id -> count of discounted units
    for line, _idx in units[:free_units]:
        discounted[line.id] = discounted.get(line.id, 0) + 1

    targets = [DiscountTarget(line_id=line_id, quantity=qty) for line_id, qty in discounted.items()]
    message = config.labels.nl

    return DiscountResult(
        candidates=[
            DiscountCandidate(
                message=message,
                targets=targets,
                percentage=get_pct,
            )
        ]
    )


def calculate_free_gift(config: OfferConfig, lines: list[CartLine]) -> DiscountResult:
    """Free gift: 100% on gift line when condition met + _mq_gift attribute matches."""
    if not config.free_gift:
        return DiscountResult()

    gift = config.free_gift
    eligible = _eligible_lines(config, lines)

    # Condition: qty (excluding gift line) >= min_qty, or subtotal >= min_subtotal
    non_gift_lines = [line for line in eligible if line.variant_id != gift.gift_variant_id]
    condition = False

    if gift.min_qty is not None:
        total_qty = sum(line.quantity for line in non_gift_lines)
        condition = total_qty >= gift.min_qty

    if gift.min_subtotal is not None:
        subtotal_cents = sum(line.price_cents * line.quantity for line in non_gift_lines)
        min_subtotal_cents = int((Decimal(gift.min_subtotal) * 100).quantize(Decimal("1")))
        condition = subtotal_cents >= min_subtotal_cents

    if not condition:
        return DiscountResult()

    # Find gift line: variant matches AND attribute _mq_gift == offer_id
    gift_lines = [
        line
        for line in lines
        if line.variant_id == gift.gift_variant_id and line.attributes.get("_mq_gift") == config.offer_id
    ]
    if not gift_lines:
        return DiscountResult()

    # 100% on 1 unit of gift line
    gift_line = gift_lines[0]
    targets = [DiscountTarget(line_id=gift_line.id, quantity=1)]
    message = config.labels.nl

    return DiscountResult(
        candidates=[
            DiscountCandidate(
                message=message,
                targets=targets,
                percentage=Decimal("100.0"),
            )
        ]
    )


def calculate_discount(config: OfferConfig, lines: list[CartLine]) -> DiscountResult:
    """Calculate discount based on offer kind."""
    if config.kind == "volume":
        return calculate_volume(config, lines)
    elif config.kind == "bogo":
        return calculate_bogo(config, lines)
    elif config.kind == "free_gift":
        return calculate_free_gift(config, lines)
    return DiscountResult()


def format_output(result: DiscountResult) -> dict[str, Any]:
    """Format result as Shopify Function output operations."""
    if not result.has_operations:
        return {"operations": []}

    operations = []
    for candidate in result.candidates:
        targets = []
        for t in candidate.targets:
            target: dict[str, Any] = {"cartLine": {"id": t.line_id}}
            if t.quantity is not None:
                target["cartLine"]["quantity"] = t.quantity
            targets.append(target)

        operations.append(
            {
                "productDiscountsAdd": {
                    "candidates": [
                        {
                            "message": candidate.message[:50],
                            "targets": targets,
                            "value": {"percentage": {"value": float(candidate.percentage)}},
                        }
                    ],
                    "selectionStrategy": "FIRST",
                }
            }
        )

    return {"operations": operations}
