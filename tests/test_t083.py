"""Tests for T-083: unit price calculation + display."""

from decimal import Decimal
from pathlib import Path

import pytest

from apps.compliance.unit_price import (
    REFERENCE_UNIT,
    UNIT_FACTORS,
    format_unit_price,
    get_reference_unit,
    is_unit_price_required,
    unit_price,
)

EXTENSIONS_DIR = Path(__file__).parent.parent / "extensions" / "theme-blocks"
BLOCK_FILE = EXTENSIONS_DIR / "blocks" / "mq-price.liquid"


# ── Unit price calculation tests ──────────────────────────────────────────


class TestUnitPriceCalculation:
    def test_milliliters_to_liters(self):
        """30 ml at €8.99 → €299.67 per liter."""
        result = unit_price(
            total=Decimal("8.99"),
            qty=1,
            net_quantity=Decimal("30"),
            unit="ml",
        )
        # 8.99 / (30 * 0.001) = 8.99 / 0.03 = 299.67
        assert result == Decimal("299.67")

    def test_grams_to_kilograms(self):
        """500 g at €4.50 → €9.00 per kilogram."""
        result = unit_price(
            total=Decimal("4.50"),
            qty=1,
            net_quantity=Decimal("500"),
            unit="g",
        )
        # 4.50 / (500 * 0.001) = 4.50 / 0.5 = 9.00
        assert result == Decimal("9.00")

    def test_liters_direct(self):
        """2 l at €5.99 → €2.995 per liter."""
        result = unit_price(
            total=Decimal("5.99"),
            qty=1,
            net_quantity=Decimal("2"),
            unit="l",
        )
        # 5.99 / (2 * 1) = 5.99 / 2 = 2.995 → 3.00
        assert result == Decimal("3.00")

    def test_quantity_multiplier(self):
        """2 × 500 ml at €9.99 → €9.99 per liter."""
        result = unit_price(
            total=Decimal("9.99"),
            qty=2,
            net_quantity=Decimal("500"),
            unit="ml",
        )
        # 9.99 / (500 * 2 * 0.001) = 9.99 / 1.0 = 9.99
        assert result == Decimal("9.99")

    def test_centimeters_to_meters(self):
        """100 cm at €15.99 → €15.99 per meter."""
        result = unit_price(
            total=Decimal("15.99"),
            qty=1,
            net_quantity=Decimal("100"),
            unit="cm",
        )
        # 15.99 / (100 * 0.01) = 15.99 / 1.0 = 15.99
        assert result == Decimal("15.99")

    def test_square_meters(self):
        """2 m2 at €25.00 → €12.50 per m2."""
        result = unit_price(
            total=Decimal("25.00"),
            qty=1,
            net_quantity=Decimal("2"),
            unit="m2",
        )
        assert result == Decimal("12.50")

    def test_rounding_half_up(self):
        """Rounding uses ROUND_HALF_UP (07 §2.3)."""
        result = unit_price(
            total=Decimal("1.00"),
            qty=1,
            net_quantity=Decimal("3"),
            unit="ml",
        )
        # 1.00 / 0.003 = 333.333... → 333.33
        assert result == Decimal("333.33")

    def test_rounding_edge(self):
        """Exact .005 rounds up."""
        result = unit_price(
            total=Decimal("1.00"),
            qty=1,
            net_quantity=Decimal("4"),
            unit="ml",
        )
        # 1.00 / 0.004 = 250.00
        assert result == Decimal("250.00")

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            unit_price(
                total=Decimal("1.00"),
                qty=1,
                net_quantity=Decimal("1"),
                unit="oz",
            )

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="positive"):
            unit_price(
                total=Decimal("1.00"),
                qty=0,
                net_quantity=Decimal("1"),
                unit="ml",
            )


# ── Reference unit tests ──────────────────────────────────────────────────


class TestReferenceUnit:
    def test_all_units_have_reference(self):
        for unit in UNIT_FACTORS:
            ref = get_reference_unit(unit)
            assert ref in REFERENCE_UNIT.values()

    def test_ml_references_liter(self):
        assert get_reference_unit("ml") == "l"

    def test_g_references_kilogram(self):
        assert get_reference_unit("g") == "kg"

    def test_cm_references_meter(self):
        assert get_reference_unit("cm") == "m"

    def test_m2_references_itself(self):
        assert get_reference_unit("m2") == "m²"

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            get_reference_unit("oz")


# ── Format tests ──────────────────────────────────────────────────────────


class TestFormatUnitPrice:
    def test_format_ml(self):
        result = format_unit_price(Decimal("299.67"), "ml")
        assert result == "€ 299.67 / l"

    def test_format_g(self):
        result = format_unit_price(Decimal("9.00"), "g")
        assert result == "€ 9.00 / kg"

    def test_format_m2(self):
        result = format_unit_price(Decimal("12.50"), "m2")
        assert result == "€ 12.50 / m²"


# ── Required check tests ──────────────────────────────────────────────────


class TestIsUnitPriceRequired:
    def test_required_when_weight(self):
        assert is_unit_price_required(Decimal("500"), "g") is True

    def test_required_when_volume(self):
        assert is_unit_price_required(Decimal("30"), "ml") is True

    def test_not_required_when_no_net_quantity(self):
        assert is_unit_price_required(None, "ml") is False

    def test_not_required_when_zero(self):
        assert is_unit_price_required(Decimal("0"), "ml") is False

    def test_not_required_when_no_unit(self):
        assert is_unit_price_required(Decimal("500"), None) is False


# ── Liquid block tests ────────────────────────────────────────────────────


class TestMqPriceLiquid:
    def test_block_exists(self):
        assert BLOCK_FILE.exists()

    def test_shows_unit_price(self):
        content = BLOCK_FILE.read_text()
        assert "unit_price" in content
        assert "reference_unit" in content

    def test_unit_price_smaller_font(self):
        """Unit price must be in smaller font, never bolder than price (07 §2.3)."""
        content = BLOCK_FILE.read_text()
        assert "mq-price__unit" in content

    def test_shows_prior_price(self):
        content = BLOCK_FILE.read_text()
        assert "prior_price" in content
        assert "mq-price__prior" in content

    def test_shows_savings_percentage(self):
        content = BLOCK_FILE.read_text()
        assert "mq-price__savings" in content
