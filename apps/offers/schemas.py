"""Offer schemas — OfferConfig validation for the Discount Function.

See docs/04-extensions.md §2, §3.
The metafield $app:mosaiq.offer_config is validated against OfferConfig
BEFORE writing. Value/percentages as strings with one decimal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Tier(BaseModel):
    """Volume discount tier (04 §3)."""

    min_qty: int = Field(ge=2, le=20)
    type: Literal["percentage"] = "percentage"
    value: str  # string with one decimal, e.g. "10.0"

    @model_validator(mode="after")
    def _validate_value(self) -> Tier:
        try:
            pct = Decimal(self.value)
        except Exception as e:
            raise ValueError(f"Invalid percentage value: {self.value}") from e
        if not (Decimal("0") < pct <= Decimal("70")):
            raise ValueError(f"Percentage must be > 0 and <= 70, got {self.value}")
        # Normalize to one decimal
        self.value = f"{pct:.1f}"
        return self

    @property
    def percentage(self) -> Decimal:
        return Decimal(self.value)


class VolumeRules(BaseModel):
    """Volume rules: 1-4 tiers, min_qty and percentage strictly ascending (04 §3)."""

    tiers: list[Tier] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _validate_ascending(self) -> VolumeRules:
        for i in range(1, len(self.tiers)):
            if self.tiers[i].min_qty <= self.tiers[i - 1].min_qty:
                raise ValueError("min_qty must be strictly ascending")
            if self.tiers[i].percentage <= self.tiers[i - 1].percentage:
                raise ValueError("percentage must be strictly ascending")
        return self


class BogoRules(BaseModel):
    """BOGO rules: buy X get Y at percentage (04 §2)."""

    buy_qty: int = Field(ge=1, le=10)
    get_qty: int = Field(ge=1, le=10)
    get_percentage: str = "100.0"  # string with one decimal

    @model_validator(mode="after")
    def _validate_percentage(self) -> BogoRules:
        try:
            pct = Decimal(self.get_percentage)
        except Exception as e:
            raise ValueError(f"Invalid get_percentage: {self.get_percentage}") from e
        if not (Decimal("0") < pct <= Decimal("100")):
            raise ValueError(f"get_percentage must be > 0 and <= 100, got {self.get_percentage}")
        self.get_percentage = f"{pct:.1f}"
        return self


class GiftRules(BaseModel):
    """Free gift rules (04 §2)."""

    gift_variant_id: str
    min_qty: int | None = Field(default=None, ge=1, le=50)
    min_subtotal: str | None = None  # decimal string or None


class OfferLabels(BaseModel):
    """Labels per language (04 §2)."""

    nl: str = Field(max_length=50)
    en: str = Field(max_length=50)
    de: str = Field(max_length=50)


class OfferConfig(BaseModel):
    """Full offer config metafield (04 §2)."""

    offer_id: str
    kind: Literal["volume", "bogo", "free_gift"]
    product_ids: list[str] = Field(min_length=1)
    tiers: list[Tier] | None = None
    bogo: BogoRules | None = None
    free_gift: GiftRules | None = None
    labels: OfferLabels

    @model_validator(mode="after")
    def _validate_kind_blocks(self) -> OfferConfig:
        """Only the block matching kind is filled; the others are null."""
        if self.kind == "volume":
            if not self.tiers:
                raise ValueError("volume kind requires tiers")
            if self.bogo is not None or self.free_gift is not None:
                raise ValueError("volume kind must not have bogo/free_gift blocks")
        elif self.kind == "bogo":
            if self.bogo is None:
                raise ValueError("bogo kind requires bogo block")
            if self.tiers is not None or self.free_gift is not None:
                raise ValueError("bogo kind must not have tiers/free_gift blocks")
        elif self.kind == "free_gift":
            if self.free_gift is None:
                raise ValueError("free_gift kind requires free_gift block")
            if self.tiers is not None or self.bogo is not None:
                raise ValueError("free_gift kind must not have tiers/bogo blocks")
        return self
