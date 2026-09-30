"""GPSR validation — General Product Safety Regulation (art. 19).

See docs/07-compliance.md §5.
GpsrInfo.complete = True if all required fields are filled.
publish refuses without complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GpsrInfo:
    """GPSR compliance information for a product."""

    # Manufacturer (required)
    manufacturer_name: str = ""
    manufacturer_address: str = ""
    manufacturer_email: str = ""

    # EU responsible person (required if manufacturer_in_eu = False)
    manufacturer_in_eu: bool = True
    eu_rp_name: str = ""
    eu_rp_address: str = ""
    eu_rp_email: str = ""

    # Product identifier (required)
    product_identifier: str = ""

    # Safety warnings (required for content language OR no_warnings_confirmed)
    warnings: str = ""
    no_warnings_confirmed: bool = False

    # Metadata
    content_locale: str = "nl"

    @property
    def complete(self) -> bool:
        """Check if GPSR is complete per 07 §5."""
        # Manufacturer fields required
        if not self.manufacturer_name or not self.manufacturer_address or not self.manufacturer_email:
            return False

        # EU responsible person required if manufacturer not in EU
        if not self.manufacturer_in_eu and (not self.eu_rp_name or not self.eu_rp_address or not self.eu_rp_email):
            return False

        # Product identifier required
        if not self.product_identifier:
            return False

        # Warnings required OR confirmed not needed
        return bool(self.warnings or self.no_warnings_confirmed)

    @property
    def missing_fields(self) -> list[str]:
        """List of missing required fields."""
        missing = []

        if not self.manufacturer_name:
            missing.append("manufacturer_name")
        if not self.manufacturer_address:
            missing.append("manufacturer_address")
        if not self.manufacturer_email:
            missing.append("manufacturer_email")

        if not self.manufacturer_in_eu:
            if not self.eu_rp_name:
                missing.append("eu_rp_name")
            if not self.eu_rp_address:
                missing.append("eu_rp_address")
            if not self.eu_rp_email:
                missing.append("eu_rp_email")

        if not self.product_identifier:
            missing.append("product_identifier")

        if not self.warnings and not self.no_warnings_confirmed:
            missing.append("warnings")

        return missing

    @classmethod
    def from_metafield(cls, data: dict[str, Any] | None) -> GpsrInfo:
        """Create GpsrInfo from metafield value dict."""
        if not data:
            return cls()

        return cls(
            manufacturer_name=data.get("manufacturer_name", ""),
            manufacturer_address=data.get("manufacturer_address", ""),
            manufacturer_email=data.get("manufacturer_email", ""),
            manufacturer_in_eu=data.get("manufacturer_in_eu", True),
            eu_rp_name=data.get("eu_rp_name", ""),
            eu_rp_address=data.get("eu_rp_address", ""),
            eu_rp_email=data.get("eu_rp_email", ""),
            product_identifier=data.get("product_identifier", ""),
            warnings=data.get("warnings", ""),
            no_warnings_confirmed=data.get("no_warnings_confirmed", False),
            content_locale=data.get("content_locale", "nl"),
        )

    def to_metafield(self) -> dict[str, Any]:
        """Convert to metafield value dict."""
        return {
            "manufacturer_name": self.manufacturer_name,
            "manufacturer_address": self.manufacturer_address,
            "manufacturer_email": self.manufacturer_email,
            "manufacturer_in_eu": self.manufacturer_in_eu,
            "eu_rp_name": self.eu_rp_name,
            "eu_rp_address": self.eu_rp_address,
            "eu_rp_email": self.eu_rp_email,
            "product_identifier": self.product_identifier,
            "warnings": self.warnings,
            "no_warnings_confirmed": self.no_warnings_confirmed,
            "content_locale": self.content_locale,
        }


def check_gpsr_for_publish(gpsr: GpsrInfo) -> tuple[bool, str]:
    """Check if GPSR is complete for publishing.

    Returns:
        (allowed, message) — allowed=False if GPSR incomplete
    """
    if not gpsr.complete:
        missing = gpsr.missing_fields
        return False, f"GPSR incomplete: missing {', '.join(missing)}"
    return True, ""


def get_gpsr_compliance_score_impact(gpsr: GpsrInfo) -> int:
    """Get compliance score impact for GPSR (07 §9).

    Returns -20 if GPSR incomplete, 0 if complete.
    """
    return -20 if not gpsr.complete else 0
