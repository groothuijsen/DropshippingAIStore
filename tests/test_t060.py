"""Tests for T-060: billing — Subscription, UsageCounter, TrialLedger, limits, plans."""

import hashlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.limits import (
    consume,
    get_current_period_start,
    get_usage_summary,
    release,
    reserve,
)
from apps.billing.models import Subscription, TrialLedger, UsageCounter
from apps.billing.plans import (
    PLAN_LIMITS,
    TRIAL_DAYS,
    get_plan_limits,
    get_plan_name,
    get_plan_price,
    get_replacement_behavior,
    is_upgrade,
)
from apps.billing.tasks import (
    get_trial_days_for_domain,
    record_trial_started,
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


@pytest.fixture
def starter_subscription(shop):
    return Subscription.objects.create(
        shop=shop,
        plan="starter",
        status="active",
    )


# ── Plans data tests ──────────────────────────────────────────────────────


class TestPlans:
    def test_plan_limits_exist(self):
        assert "starter" in PLAN_LIMITS
        assert "pro" in PLAN_LIMITS
        assert "agency" in PLAN_LIMITS

    def test_starter_limits(self):
        limits = get_plan_limits("starter")
        assert limits["store_generations"] == 3
        assert limits["ai_images"] == 30
        assert limits["live_pages"] == 15

    def test_pro_limits(self):
        limits = get_plan_limits("pro")
        assert limits["store_generations"] == 15
        assert limits["ai_images"] == 150

    def test_agency_limits(self):
        limits = get_plan_limits("agency")
        assert limits["store_generations"] == 50
        assert limits["live_pages"] is None  # unlimited

    def test_unknown_plan_defaults_to_starter(self):
        limits = get_plan_limits("unknown")
        assert limits["store_generations"] == 3

    def test_plan_prices(self):
        assert get_plan_price("starter", "every_30_days") == Decimal("29.00")
        assert get_plan_price("pro", "every_30_days") == Decimal("79.00")
        assert get_plan_price("agency", "every_30_days") == Decimal("199.00")

    def test_annual_prices(self):
        assert get_plan_price("starter", "annual") == Decimal("290.00")
        assert get_plan_price("pro", "annual") == Decimal("790.00")

    def test_plan_names(self):
        assert get_plan_name("starter") == "Mosaiq Starter"
        assert get_plan_name("pro", "annual") == "Mosaiq Pro (annual)"

    def test_is_upgrade(self):
        assert is_upgrade("starter", "pro") is True
        assert is_upgrade("pro", "agency") is True
        assert is_upgrade("pro", "starter") is False
        assert is_upgrade("starter", "starter") is False

    def test_replacement_behavior(self):
        assert get_replacement_behavior("starter", "pro") == "APPLY_IMMEDIATELY"
        assert get_replacement_behavior("pro", "starter") == "APPLY_ON_NEXT_BILLING_CYCLE"

    def test_trial_days(self):
        assert TRIAL_DAYS == 7


# ── Reservation tests ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestReservation:
    def test_reserve_within_limit(self, shop, starter_subscription):
        result = reserve(shop, "store_generations", 1)
        assert result.allowed is True
        assert result.limit == 3

    def test_reserve_at_limit(self, shop, starter_subscription):
        reserve(shop, "store_generations", 3)
        result = reserve(shop, "store_generations", 1)
        assert result.allowed is False

    def test_reserve_multiple(self, shop, starter_subscription):
        result = reserve(shop, "store_generations", 2)
        assert result.allowed is True
        assert result.remaining == 1

    def test_reserve_ai_images(self, shop, starter_subscription):
        result = reserve(shop, "ai_images", 10)
        assert result.allowed is True
        assert result.limit == 30

    def test_release_reduces_reservation(self, shop, starter_subscription):
        reserve(shop, "store_generations", 2)
        release(shop, "store_generations", 1)
        counter = UsageCounter.objects.get(shop=shop, period_start=get_current_period_start())
        assert counter.reserved_store_generations == 1

    def test_consume_increments_and_decrements_reserved(self, shop, starter_subscription):
        reserve(shop, "store_generations", 2)
        consume(shop, "store_generations", 1)
        counter = UsageCounter.objects.get(shop=shop, period_start=get_current_period_start())
        assert counter.store_generations == 1
        assert counter.reserved_store_generations == 1

    def test_unknown_resource_raises(self, shop, starter_subscription):
        with pytest.raises(ValueError, match="Unknown resource"):
            reserve(shop, "bad_resource", 1)

    def test_no_subscription_defaults_to_starter(self, shop):
        result = reserve(shop, "store_generations", 1)
        assert result.allowed is True
        assert result.limit == 3

    def test_concurrent_reservation_cannot_exceed(self, shop, starter_subscription):
        """Two parallel reservations cannot exceed the limit."""
        r1 = reserve(shop, "store_generations", 2)
        r2 = reserve(shop, "store_generations", 2)
        assert r1.allowed is True
        assert r2.allowed is False


# ── TrialLedger tests ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestTrialLedger:
    def test_new_domain_gets_trial(self):
        assert get_trial_days_for_domain("new-store.myshopify.com") == 7

    def test_existing_domain_no_trial(self):
        domain = "existing-store.myshopify.com"
        record_trial_started(domain)
        assert get_trial_days_for_domain(domain) == 0

    def test_domain_hash_case_insensitive(self):
        record_trial_started("Mixed-Case.Store")
        assert get_trial_days_for_domain("mixed-case.store") == 0

    def test_ledger_no_shop_fk(self):
        """TrialLedger has no FK to Shop — persists after shop/redact."""
        record_trial_started("persist-store.myshopify.com")
        ledger = TrialLedger.objects.first()
        assert ledger is not None
        assert ledger.domain_sha256 == hashlib.sha256(b"persist-store.myshopify.com").hexdigest()


# ── Usage summary tests ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestUsageSummary:
    def test_summary_structure(self, shop, starter_subscription):
        summary = get_usage_summary(shop)
        assert summary["plan"] == "starter"
        assert "store_generations" in summary["usage"]
        assert "ai_images" in summary["usage"]
        assert "live_pages" in summary["usage"]

    def test_summary_reflects_reservations(self, shop, starter_subscription):
        reserve(shop, "store_generations", 2)
        summary = get_usage_summary(shop)
        assert summary["usage"]["store_generations"]["reserved"] == 2
