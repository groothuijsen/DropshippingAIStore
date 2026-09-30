"""Tests for T-070: Discount Function config validation + discount logic.

Minimum cases per docs/04-extensions.md §2 Tests:
no tier reached, lowest tier, highest tier, mixed products, BOGO with an
odd quantity, gift without condition, gift with condition, gift attribute
from another offer.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from apps.offers.discount_logic import (
    CartLine,
    calculate_bogo,
    calculate_discount,
    calculate_free_gift,
    calculate_volume,
    format_output,
)
from apps.offers.schemas import (
    BogoRules,
    GiftRules,
    OfferConfig,
    OfferLabels,
    Tier,
    VolumeRules,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


def _labels():
    return OfferLabels(nl="Bundelkorting", en="Bundle discount", de="Bundelrabatt")


def _volume_config(tiers=None, product_ids=None):
    if tiers is None:
        tiers = [
            {"min_qty": 2, "value": "10.0"},
            {"min_qty": 3, "value": "15.0"},
        ]
    return OfferConfig(
        offer_id="offer-1",
        kind="volume",
        product_ids=product_ids or ["gid://shopify/Product/1"],
        tiers=tiers,
        labels=_labels(),
    )


def _bogo_config(buy_qty=1, get_qty=1, get_percentage="100.0", product_ids=None):
    return OfferConfig(
        offer_id="offer-2",
        kind="bogo",
        product_ids=product_ids or ["gid://shopify/Product/1"],
        bogo=BogoRules(buy_qty=buy_qty, get_qty=get_qty, get_percentage=get_percentage),
        labels=_labels(),
    )


def _gift_config(min_qty=2, min_subtotal=None, gift_variant="gid://shopify/ProductVariant/9", product_ids=None):
    return OfferConfig(
        offer_id="offer-3",
        kind="free_gift",
        product_ids=product_ids or ["gid://shopify/Product/1"],
        free_gift=GiftRules(
            gift_variant_id=gift_variant,
            min_qty=min_qty,
            min_subtotal=min_subtotal,
        ),
        labels=_labels(),
    )


def _line(
    line_id="L1",
    product_id="gid://shopify/Product/1",
    variant_id="gid://shopify/ProductVariant/1",
    quantity=1,
    price_cents=1000,
    attributes=None,
):
    return CartLine(
        id=line_id,
        product_id=product_id,
        variant_id=variant_id,
        quantity=quantity,
        price_cents=price_cents,
        attributes=attributes or {},
    )


# ── OfferConfig schema tests (config metafield test first) ────────────────


class TestOfferConfig:
    def test_volume_config_valid(self):
        config = _volume_config()
        assert config.kind == "volume"
        assert len(config.tiers) == 2

    def test_bogo_config_valid(self):
        config = _bogo_config()
        assert config.kind == "bogo"
        assert config.bogo is not None

    def test_gift_config_valid(self):
        config = _gift_config()
        assert config.kind == "free_gift"
        assert config.free_gift is not None

    def test_volume_requires_tiers(self):
        with pytest.raises(ValidationError):
            OfferConfig(
                offer_id="o",
                kind="volume",
                product_ids=["p1"],
                tiers=None,
                labels=_labels(),
            )

    def test_volume_rejects_bogo_block(self):
        with pytest.raises(ValidationError):
            OfferConfig(
                offer_id="o",
                kind="volume",
                product_ids=["p1"],
                tiers=[{"min_qty": 2, "value": "10.0"}],
                bogo=BogoRules(buy_qty=1, get_qty=1),
                labels=_labels(),
            )

    def test_percentage_must_be_1_to_70(self):
        with pytest.raises(ValidationError):
            Tier(min_qty=2, value="0.0")
        with pytest.raises(ValidationError):
            Tier(min_qty=2, value="70.1")

    def test_tiers_strictly_ascending_min_qty(self):
        with pytest.raises(ValidationError):
            VolumeRules(
                tiers=[
                    {"min_qty": 3, "value": "10.0"},
                    {"min_qty": 2, "value": "15.0"},
                ]
            )

    def test_tiers_strictly_ascending_percentage(self):
        with pytest.raises(ValidationError):
            VolumeRules(
                tiers=[
                    {"min_qty": 2, "value": "15.0"},
                    {"min_qty": 3, "value": "10.0"},
                ]
            )

    def test_max_4_tiers(self):
        tiers = [{"min_qty": 2 + i, "value": f"{10 + i * 5}.0"} for i in range(5)]
        with pytest.raises(ValidationError):
            VolumeRules(tiers=tiers)

    def test_percentage_normalized_to_one_decimal(self):
        tier = Tier(min_qty=2, value="10")
        assert tier.value == "10.0"

    def test_labels_max_50_chars(self):
        with pytest.raises(ValidationError):
            OfferLabels(nl="X" * 51, en="ok", de="ok")


# ── Volume discount tests ─────────────────────────────────────────────────


class TestVolume:
    def test_no_tier_reached(self):
        """qty 1 < min_qty 2 → no operations."""
        config = _volume_config()
        lines = [_line(quantity=1)]
        result = calculate_volume(config, lines)
        assert result.has_operations is False

    def test_lowest_tier(self):
        """qty 2 → tier 1 (10%)."""
        config = _volume_config()
        lines = [_line(quantity=2)]
        result = calculate_volume(config, lines)
        assert result.has_operations is True
        assert result.candidates[0].percentage == Decimal("10.0")

    def test_highest_tier(self):
        """qty 5 → tier 2 (15%)."""
        config = _volume_config()
        lines = [_line(quantity=5)]
        result = calculate_volume(config, lines)
        assert result.has_operations is True
        assert result.candidates[0].percentage == Decimal("15.0")

    def test_mixed_products(self):
        """Two products, quantities summed."""
        config = _volume_config(product_ids=["gid://shopify/Product/1", "gid://shopify/Product/2"])
        lines = [
            _line(line_id="L1", product_id="gid://shopify/Product/1", quantity=1),
            _line(line_id="L2", product_id="gid://shopify/Product/2", quantity=2),
        ]
        result = calculate_volume(config, lines)
        assert result.has_operations is True
        assert result.candidates[0].percentage == Decimal("15.0")  # 3 total

    def test_ineligible_products_excluded(self):
        """Product not in product_ids doesn't count."""
        config = _volume_config()
        lines = [
            _line(line_id="L1", quantity=2),
            _line(line_id="L2", product_id="gid://shopify/Product/99", quantity=5),
        ]
        result = calculate_volume(config, lines)
        assert result.has_operations is True
        assert result.candidates[0].percentage == Decimal("10.0")  # only L1 counts

    def test_targets_all_eligible_lines(self):
        config = _volume_config()
        lines = [
            _line(line_id="L1", quantity=1),
            _line(line_id="L2", quantity=1),
        ]
        result = calculate_volume(config, lines)
        assert len(result.candidates[0].targets) == 2


# ── BOGO tests ────────────────────────────────────────────────────────────


class TestBogo:
    def test_bogo_odd_quantity(self):
        """buy 1 get 1, qty 3 → 1 free unit (floor(3/2)*1)."""
        config = _bogo_config()
        lines = [_line(quantity=3)]
        result = calculate_bogo(config, lines)
        assert result.has_operations is True
        total_discounted = sum(t.quantity for t in result.candidates[0].targets)
        assert total_discounted == 1

    def test_bogo_even_quantity(self):
        """buy 1 get 1, qty 4 → 2 free units."""
        config = _bogo_config()
        lines = [_line(quantity=4)]
        result = calculate_bogo(config, lines)
        assert result.has_operations is True
        total_discounted = sum(t.quantity for t in result.candidates[0].targets)
        assert total_discounted == 2

    def test_bogo_cheapest_units_discounted(self):
        """Cheapest units get the discount."""
        config = _bogo_config()
        lines = [
            _line(line_id="L1", quantity=2, price_cents=2000),  # expensive
            _line(line_id="L2", quantity=2, price_cents=1000),  # cheap
        ]
        result = calculate_bogo(config, lines)
        assert result.has_operations is True
        # floor(4/2)*1 = 2 free units, both from L2 (cheapest)
        assert len(result.candidates[0].targets) == 1
        assert result.candidates[0].targets[0].line_id == "L2"
        assert result.candidates[0].targets[0].quantity == 2

    def test_bogo_insufficient_units(self):
        """qty 1 < group 2 → no operations."""
        config = _bogo_config()
        lines = [_line(quantity=1)]
        result = calculate_bogo(config, lines)
        assert result.has_operations is False

    def test_bogo_partial_percentage(self):
        """get_percentage 50 → 50% on free units."""
        config = _bogo_config(get_percentage="50.0")
        lines = [_line(quantity=2)]
        result = calculate_bogo(config, lines)
        assert result.has_operations is True
        assert result.candidates[0].percentage == Decimal("50.0")


# ── Free gift tests ───────────────────────────────────────────────────────


class TestFreeGift:
    def test_gift_without_condition(self):
        """qty 1 < min_qty 2 → no operations."""
        config = _gift_config(min_qty=2)
        lines = [
            _line(line_id="L1", quantity=1),
            _line(
                line_id="L2",
                variant_id="gid://shopify/ProductVariant/9",
                quantity=1,
                attributes={"_mq_gift": "offer-3"},
            ),
        ]
        result = calculate_free_gift(config, lines)
        assert result.has_operations is False

    def test_gift_with_condition(self):
        """qty 2 >= min_qty 2 + gift line present → 100% on gift."""
        config = _gift_config(min_qty=2)
        lines = [
            _line(line_id="L1", quantity=2),
            _line(
                line_id="L2",
                variant_id="gid://shopify/ProductVariant/9",
                quantity=1,
                attributes={"_mq_gift": "offer-3"},
            ),
        ]
        result = calculate_free_gift(config, lines)
        assert result.has_operations is True
        assert result.candidates[0].percentage == Decimal("100.0")
        assert result.candidates[0].targets[0].quantity == 1

    def test_gift_attribute_from_other_offer(self):
        """Gift line with _mq_gift from another offer → no discount."""
        config = _gift_config(min_qty=2)
        lines = [
            _line(line_id="L1", quantity=2),
            _line(
                line_id="L2",
                variant_id="gid://shopify/ProductVariant/9",
                quantity=1,
                attributes={"_mq_gift": "other-offer"},
            ),
        ]
        result = calculate_free_gift(config, lines)
        assert result.has_operations is False

    def test_gift_min_subtotal(self):
        """Subtotal condition."""
        config = _gift_config(min_qty=None, min_subtotal="50.00")
        lines = [
            _line(line_id="L1", quantity=1, price_cents=6000),  # €60 >= €50
            _line(
                line_id="L2",
                variant_id="gid://shopify/ProductVariant/9",
                quantity=1,
                attributes={"_mq_gift": "offer-3"},
            ),
        ]
        result = calculate_free_gift(config, lines)
        assert result.has_operations is True

    def test_gift_min_subtotal_not_met(self):
        config = _gift_config(min_qty=None, min_subtotal="50.00")
        lines = [
            _line(line_id="L1", quantity=1, price_cents=4000),  # €40 < €50
            _line(
                line_id="L2",
                variant_id="gid://shopify/ProductVariant/9",
                quantity=1,
                attributes={"_mq_gift": "offer-3"},
            ),
        ]
        result = calculate_free_gift(config, lines)
        assert result.has_operations is False


# ── Dispatcher + output tests ─────────────────────────────────────────────


class TestDispatcher:
    def test_calculate_discount_dispatches_volume(self):
        config = _volume_config()
        result = calculate_discount(config, [_line(quantity=2)])
        assert result.has_operations is True

    def test_calculate_discount_dispatches_bogo(self):
        config = _bogo_config()
        result = calculate_discount(config, [_line(quantity=2)])
        assert result.has_operations is True

    def test_calculate_discount_dispatches_gift(self):
        config = _gift_config(min_qty=2)
        lines = [
            _line(quantity=2),
            _line(line_id="G", variant_id="gid://shopify/ProductVariant/9", attributes={"_mq_gift": "offer-3"}),
        ]
        result = calculate_discount(config, lines)
        assert result.has_operations is True

    def test_format_output_no_operations(self):
        result = calculate_volume(_volume_config(), [_line(quantity=1)])
        output = format_output(result)
        assert output == {"operations": []}

    def test_format_output_volume(self):
        result = calculate_volume(_volume_config(), [_line(quantity=2)])
        output = format_output(result)
        assert len(output["operations"]) == 1
        op = output["operations"][0]["productDiscountsAdd"]
        assert op["selectionStrategy"] == "FIRST"
        candidate = op["candidates"][0]
        assert candidate["value"]["percentage"]["value"] == 10.0
        assert candidate["message"] == "Bundelkorting"

    def test_format_output_message_max_50(self):
        config = _volume_config()
        config.labels.nl = "X" * 60
        result = calculate_volume(config, [_line(quantity=2)])
        output = format_output(result)
        assert len(output["operations"][0]["productDiscountsAdd"]["candidates"][0]["message"]) <= 50

    def test_format_output_bogo_targets_have_quantity(self):
        result = calculate_bogo(_bogo_config(), [_line(quantity=2)])
        output = format_output(result)
        target = output["operations"][0]["productDiscountsAdd"]["candidates"][0]["targets"][0]
        assert "quantity" in target["cartLine"]

    def test_format_output_volume_targets_no_quantity(self):
        result = calculate_volume(_volume_config(), [_line(quantity=2)])
        output = format_output(result)
        target = output["operations"][0]["productDiscountsAdd"]["candidates"][0]["targets"][0]
        assert "quantity" not in target["cartLine"]
