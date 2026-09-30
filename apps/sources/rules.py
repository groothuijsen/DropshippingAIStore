"""Source detection rules — determines which app manages a product.

See docs/06-dropship-integrations.md §4.3.

Rules are ordered strongest-first. First match on a rule with
fulfillment_*/location_name wins → detected_by = fulfillment_location.
Otherwise vendor/sku rule → vendor/sku.
Otherwise onboarding or unknown_app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRule:
    source: str
    signal: str  # fulfillment_handle, location_name, vendor, sku
    pattern: str
    verified: bool


# Rules from 06 §4.3, strongest first
SOURCE_RULES: list[SourceRule] = [
    SourceRule("dsers", "fulfillment_handle", r"^dsers-fulfillment-service$", True),
    SourceRule("printify", "fulfillment_handle", r"^printify$", False),
    SourceRule("printify", "location_name", r"(?i)^printify$", True),
    SourceRule("printful", "location_name", r"(?i)^printful$", True),
    SourceRule("autods", "location_name", r"(?i)^autods", True),
    SourceRule("zendrop", "location_name", r"(?i)^zendrop", True),
    SourceRule("cj", "location_name", r"(?i)cj ?dropshipping|^cj\b", False),
    SourceRule("printify", "vendor", r"(?i)^printify$", True),
    SourceRule("cj", "sku", r"^CJ[A-Z0-9]{4,}", False),
]

# Fields that are ALWAYS locked for non-Mosaiq products (06 §3)
ALWAYS_LOCKED_FIELDS = [
    "title",
    "price",
    "compareAtPrice",
    "variants",
    "options",
    "sku",
    "barcode",
    "inventoryQuantity",
    "descriptionHtml",
    "tags",
    "vendor",
    "productType",
    "media",
    "seoTitle",
    "seoDescription",
]

# Fields Mosaiq may always write (06 §3)
ALWAYS_WRITABLE_FIELDS = ["templateSuffix", "$app:mosaiq"]


def get_locked_fields(source: str) -> list[str]:
    """Return the list of locked fields for a given source."""
    if source == "manual":
        return []  # Fully editable
    return [f for f in ALWAYS_LOCKED_FIELDS if f not in ALWAYS_WRITABLE_FIELDS]


def detect_source(
    *,
    fulfillment_handle: str | None = None,
    location_name: str | None = None,
    vendor: str | None = None,
    sku: str | None = None,
    onboarding_apps: list[str] | None = None,
) -> tuple[str, str]:
    """Detect the source app for a product.

    Returns (source, detected_by).
    Decision order (06 §4.3): first match on fulfillment/location rules wins.
    Then vendor/sku. Otherwise onboarding. Otherwise unknown_app.
    """
    # Check fulfillment_handle and location_name rules first (strongest signal)
    for rule in SOURCE_RULES:
        if rule.signal in ("fulfillment_handle", "location_name"):
            value = fulfillment_handle if rule.signal == "fulfillment_handle" else location_name
            if value and re.match(rule.pattern, value):
                detected_by = (
                    "fulfillment_location" if rule.signal in ("fulfillment_handle", "location_name") else rule.signal
                )
                return rule.source, detected_by

    # Check vendor rules
    for rule in SOURCE_RULES:
        if rule.signal == "vendor" and vendor and re.match(rule.pattern, vendor):
            return rule.source, "vendor"

    # Check SKU rules
    for rule in SOURCE_RULES:
        if rule.signal == "sku" and sku and re.match(rule.pattern, sku):
            return rule.source, "sku"

    # Check onboarding: if merchant uses exactly one import app
    if onboarding_apps and len(onboarding_apps) == 1:
        app = onboarding_apps[0]
        if app in ("dsers", "cj", "zendrop", "autods", "printify", "printful"):
            return app, "onboarding"

    return "unknown_app", "onboarding"
