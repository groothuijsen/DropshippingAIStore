"""Tests for T-081: Omnibus prior_price + reduction + attestation."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.compliance.models import PriceAttestation, PriceHistory
from apps.compliance.pricing import (
    is_reduction_available,
    prior_price,
    reduction,
)
from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus


@pytest.fixture
def shop(db):
    now = timezone.now()
    return Shop.objects.create(
        domain="test-store.myshopify.com",
        shopify_gid="gid://shopify/Shop/123",
        access_token_encrypted=encrypt_token("shpat_test_token"),
        access_token_expires_at=now + timedelta(hours=1),
        refresh_token_encrypted=encrypt_token("shpat_refresh_token"),
        refresh_token_expires_at=now + timedelta(days=90),
        currency_code="EUR",
        status=ShopStatus.ACTIVE,
    )


VARIANT = "gid://shopify/ProductVariant/123"


def _add_history(shop, price, observed_at, market="primary"):
    return PriceHistory.objects.create(
        shop=shop,
        variant_gid=VARIANT,
        market_handle=market,
        price=Decimal(price),
        currency="EUR",
        observed_at=observed_at,
        source="webhook",
    )


# ── prior_price tests ─────────────────────────────────────────────────────


class TestPriorPrice:
    def test_no_history_returns_none(self, shop):
        result = prior_price(shop, VARIANT, Decimal("20.00"))
        assert result is None

    def test_short_history_no_attestation(self, shop):
        """History shorter than 30 days without attestation → None."""
        now = timezone.now()
        _add_history(shop, "30.00", now - timedelta(days=10))
        _add_history(shop, "20.00", now - timedelta(days=5))
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is None

    def test_short_history_with_attestation(self, shop):
        """History shorter than 30 days with attestation → uses attestation."""
        now = timezone.now()
        _add_history(shop, "30.00", now - timedelta(days=10))
        _add_history(shop, "20.00", now - timedelta(days=5))
        PriceAttestation.objects.create(
            shop=shop,
            variant_gid=VARIANT,
            lowest_price_30d=Decimal("25.00"),
            valid_until=now + timedelta(days=20),
        )
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is not None
        assert result.amount == Decimal("25.00")

    def test_attestation_expired(self, shop):
        """Expired attestation doesn't count."""
        now = timezone.now()
        _add_history(shop, "30.00", now - timedelta(days=10))
        _add_history(shop, "20.00", now - timedelta(days=5))
        PriceAttestation.objects.create(
            shop=shop,
            variant_gid=VARIANT,
            lowest_price_30d=Decimal("25.00"),
            valid_until=now - timedelta(days=1),
        )
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is None

    def test_price_increase_before_promotion(self, shop):
        """Price increase just before promotion doesn't count as prior."""
        now = timezone.now()
        # Price was 30, increased to 35, then dropped to 20
        _add_history(shop, "30.00", now - timedelta(days=40))
        _add_history(shop, "35.00", now - timedelta(days=20))
        _add_history(shop, "20.00", now - timedelta(days=5))
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is not None
        # Prior should be 30 (before the increase), not 35
        assert result.amount == Decimal("30.00")

    def test_promotion_already_running(self, shop):
        """Window lies before the promotion, not before today."""
        now = timezone.now()
        # Price 30 for a long time, then 20 for 10 days
        _add_history(shop, "30.00", now - timedelta(days=40))
        _add_history(shop, "20.00", now - timedelta(days=10))
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is not None
        assert result.amount == Decimal("30.00")

    def test_daily_snapshots_same_price(self, shop):
        """Daily snapshots with same price are collapsed."""
        now = timezone.now()
        # Reduction starts 20d ago; window = [50d ago, 20d ago)
        for days_ago in range(55, 20, -1):
            _add_history(shop, "30.00", now - timedelta(days=days_ago))
        for days_ago in range(20, 5, -1):
            _add_history(shop, "20.00", now - timedelta(days=days_ago))
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is not None
        assert result.amount == Decimal("30.00")

    def test_multiple_changes_in_window(self, shop):
        """Multiple price changes within the window → lowest counts."""
        now = timezone.now()
        _add_history(shop, "30.00", now - timedelta(days=40))
        _add_history(shop, "35.00", now - timedelta(days=35))
        _add_history(shop, "28.00", now - timedelta(days=25))
        _add_history(shop, "32.00", now - timedelta(days=20))
        _add_history(shop, "20.00", now - timedelta(days=5))
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is not None
        # Window is [reduction_start - 30, reduction_start)
        # reduction_start = when price 20 started = 5 days ago
        # window = [35 days ago, 5 days ago)
        # prices in window: 35.00 (35d), 28.00 (25d), 32.00 (20d)
        # anchor at 35d boundary: 30.00
        # lowest = 28.00
        assert result.amount == Decimal("28.00")

    def test_current_price_used_for_reduction_start(self, shop):
        """Reduction start = oldest observation in current price run."""
        now = timezone.now()
        # Anchor at 50d ago = 25.00; 30.00 in window; reduction starts 15d ago
        _add_history(shop, "25.00", now - timedelta(days=50))
        _add_history(shop, "30.00", now - timedelta(days=40))
        _add_history(shop, "20.00", now - timedelta(days=15))
        _add_history(shop, "20.00", now - timedelta(days=10))
        _add_history(shop, "20.00", now - timedelta(days=5))
        result = prior_price(shop, VARIANT, Decimal("20.00"), now=now)
        assert result is not None
        # reduction_start = 15 days ago (oldest 20.00)
        # window = [45 days ago, 15 days ago)
        # anchor at 45d boundary: 25.00 (50d ago observation)
        # in_window: 30.00 (40d ago)
        # lowest = 25.00
        assert result.amount == Decimal("25.00")


# ── reduction tests ───────────────────────────────────────────────────────


class TestReduction:
    def test_normal_reduction(self):
        result = reduction(Decimal("70.00"), Decimal("100.00"))
        assert result is not None
        assert result.percent == 30

    def test_rounding_down(self):
        """33.9% → 33 (round down)."""
        result = reduction(Decimal("66.10"), Decimal("100.00"))
        assert result is not None
        assert result.percent == 33

    def test_no_reduction_current_ge_prior(self):
        """Current ≥ prior → no reduction."""
        assert reduction(Decimal("100.00"), Decimal("100.00")) is None
        assert reduction(Decimal("100.00"), Decimal("50.00")) is None

    def test_small_reduction(self):
        result = reduction(Decimal("99.00"), Decimal("100.00"))
        assert result is not None
        assert result.percent == 1

    def test_zero_reduction(self):
        result = reduction(Decimal("0.00"), Decimal("100.00"))
        assert result is not None
        assert result.percent == 100


# ── is_reduction_available tests ──────────────────────────────────────────


class TestIsReductionAvailable:
    def test_available_with_reduction(self, shop):
        now = timezone.now()
        _add_history(shop, "30.00", now - timedelta(days=40))
        _add_history(shop, "20.00", now - timedelta(days=10))
        assert is_reduction_available(shop, VARIANT, Decimal("20.00"), now=now) is True

    def test_not_available_no_history(self, shop):
        assert is_reduction_available(shop, VARIANT, Decimal("20.00")) is False

    def test_not_available_same_price(self, shop):
        now = timezone.now()
        _add_history(shop, "20.00", now - timedelta(days=40))
        assert is_reduction_available(shop, VARIANT, Decimal("20.00"), now=now) is False
