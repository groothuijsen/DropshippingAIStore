from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing.models import FoundingDiscount
from apps.billing.plans import get_founding_price, get_plan_price
from apps.core.models import Shop

pytestmark = pytest.mark.django_db


def _make_shop(domain="found.myshopify.com"):
    return Shop.objects.create(domain=domain, currency_code="EUR", status="active")


class TestFoundingPrice:
    def test_starter_monthly_50_off(self):
        assert get_founding_price("starter", "every_30_days", 50) == Decimal("14.50")

    def test_pro_monthly_50_off(self):
        assert get_founding_price("pro", "every_30_days", 50) == Decimal("29.50")

    def test_agency_monthly_50_off(self):
        assert get_founding_price("agency", "every_30_days", 50) == Decimal("74.50")

    def test_starter_annual_50_off(self):
        assert get_founding_price("starter", "annual", 50) == Decimal("145.00")

    def test_full_price_when_zero_percent(self):
        assert get_founding_price("starter", "every_30_days", 0) == get_plan_price("starter", "every_30_days")

    def test_rounding(self):
        # 29 * 33% = 9.57 → 29 - 9.57 = 19.43
        assert get_founding_price("starter", "every_30_days", 33) == Decimal("19.43")


class TestFoundingDiscountModel:
    def test_is_active_true(self):
        shop = _make_shop()
        d = FoundingDiscount.objects.create(shop=shop, percent_off=50, valid_until=timezone.now() + timedelta(days=360))
        assert d.is_active is True

    def test_is_active_false_when_expired(self):
        shop = _make_shop()
        d = FoundingDiscount.objects.create(shop=shop, percent_off=50, valid_until=timezone.now() - timedelta(days=1))
        assert d.is_active is False

    def test_str(self):
        shop = _make_shop()
        d = FoundingDiscount.objects.create(shop=shop, percent_off=50, valid_until=timezone.now() + timedelta(days=30))
        assert "50%" in str(d) and "found.myshopify.com" in str(d)


class TestGrantCommand:
    def test_grant_creates_discount(self):
        from django.core.management import call_command
        shop = _make_shop()
        call_command("grant_founding_discount", "found.myshopify.com", "50")
        d = FoundingDiscount.objects.get(shop=shop)
        assert d.percent_off == 50

    def test_grant_updates_existing(self):
        from django.core.management import call_command
        shop = _make_shop()
        FoundingDiscount.objects.create(shop=shop, percent_off=30, valid_until=timezone.now() + timedelta(days=30))
        call_command("grant_founding_discount", "found.myshopify.com", "50")
        d = FoundingDiscount.objects.get(shop=shop)
        assert d.percent_off == 50

    def test_grant_invalid_percent(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        _make_shop()
        with pytest.raises(CommandError):
            call_command("grant_founding_discount", "found.myshopify.com", "0")

    def test_grant_unknown_shop(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with pytest.raises(CommandError):
            call_command("grant_founding_discount", "unknown.myshopify.com", "50")

    def test_grant_custom_months(self):
        from django.core.management import call_command
        shop = _make_shop()
        call_command("grant_founding_discount", "found.myshopify.com", "50", "6")
        d = FoundingDiscount.objects.get(shop=shop)
        expected_days = 6 * 30
        actual = (d.valid_until - timezone.now()).days
        assert abs(actual - expected_days) <= 1
