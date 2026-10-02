"""Section schemas for marketing content (13 §4, F19-2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CtaLink(BaseModel):
    label: str = Field(max_length=40)
    href: str = Field(max_length=200)  # @install / @early_access / anchor / path


class Hero(BaseModel):
    type: Literal["hero"] = "hero"
    eyebrow: str = Field(default="", max_length=60)
    headline: str = Field(min_length=5, max_length=70)
    sub: str = Field(min_length=10, max_length=200)
    cta_primary: CtaLink
    cta_secondary: CtaLink | None = None


class Step(BaseModel):
    title: str = Field(max_length=60)
    text: str = Field(max_length=220)


class Steps(BaseModel):
    type: Literal["steps"] = "steps"
    items: list[Step] = Field(min_length=2, max_length=6)


class Feature(BaseModel):
    icon: str = Field(default="", max_length=40)
    title: str = Field(max_length=60)
    text: str = Field(max_length=220)
    claim_ids: list[str] = Field(default_factory=list, max_length=6)


class Features(BaseModel):
    type: Literal["features"] = "features"
    items: list[Feature] = Field(min_length=1, max_length=12)


class FaqItem(BaseModel):
    q: str = Field(max_length=140)
    a: str = Field(max_length=600)


class Faq(BaseModel):
    type: Literal["faq"] = "faq"
    items: list[FaqItem] = Field(min_length=1, max_length=12)


class Cta(BaseModel):
    type: Literal["cta"] = "cta"
    headline: str = Field(max_length=70)
    sub: str = Field(default="", max_length=200)
    cta_primary: CtaLink


class PricingTable(BaseModel):
    """No copy fields for prices — rendered from plans.py in code."""

    type: Literal["pricing_table"] = "pricing_table"


class ComparisonRow(BaseModel):
    label: str = Field(max_length=60)
    mosaiq: str = Field(max_length=120)
    others: str = Field(max_length=120)


class Comparison(BaseModel):
    type: Literal["comparison"] = "comparison"
    rows: list[ComparisonRow] = Field(min_length=1, max_length=10)
    last_checked: str  # ISO date; 90-day reminder / 120-day auto-hide (F19-11)
    sources: list[str] = Field(default_factory=list, max_length=6)


SECTIONS: dict[str, type[BaseModel]] = {
    "hero": Hero,
    "steps": Steps,
    "features": Features,
    "faq": Faq,
    "cta": Cta,
    "pricing_table": PricingTable,
    "comparison": Comparison,
}


def validate_sections(sections: list[dict[str, Any]]) -> list[str]:
    """Validate every section against its schema. Returns error strings."""
    errors: list[str] = []
    for i, section in enumerate(sections):
        kind = (section or {}).get("type")
        model = SECTIONS.get(kind or "")
        if model is None:
            errors.append(f"section {i}: unknown type `{kind}`")
            continue
        try:
            model.model_validate(section)
        except Exception as exc:  # noqa: BLE001 — collect all schema errors
            errors.append(f"section {i} ({kind}): {exc}")
    return errors
