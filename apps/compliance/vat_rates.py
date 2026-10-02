"""EU VAT standard rates for the price advisor (F17).

Data: standard rates only (reduced rates not handled — the screen says so).
Source and date per row for auditability. GB is outside the EU → no rate.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# country → {rate (Decimal fraction), source, date}
VAT_STANDARD_RATES: dict[str, dict[str, Any]] = {
    "NL": {"rate": Decimal("0.21"), "source": "Belastingdienst", "date": "2026-01-01"},
    "BE": {"rate": Decimal("0.21"), "source": "FPS Financien", "date": "2026-01-01"},
    "DE": {"rate": Decimal("0.19"), "source": "Bundesministerium der Finanzen", "date": "2026-01-01"},
    "AT": {"rate": Decimal("0.20"), "source": "Bundesministerium Finanzen", "date": "2026-01-01"},
    "FR": {"rate": Decimal("0.20"), "source": "Service-Public.fr", "date": "2026-01-01"},
    "LU": {"rate": Decimal("0.17"), "source": "Administration des contributions directes", "date": "2026-01-01"},
    "IE": {"rate": Decimal("0.23"), "source": "Revenue Commissioners", "date": "2026-01-01"},
}

GB_NOT_COVERED_MESSAGE = "VAT rules for GB not covered"


def vat_rate_for(country: str) -> Decimal | None:
    """Return the standard VAT rate for a country, or None (not covered)."""
    row = VAT_STANDARD_RATES.get((country or "").upper())
    return row["rate"] if row else None
