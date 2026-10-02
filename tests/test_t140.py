"""Tests for T-140: DeliveryProfile, DeliveryOverride, estimate()."""

from decimal import Decimal

import pytest

from apps.compliance.delivery import estimate
from apps.compliance.models import DeliveryOverride, DeliveryProfile
from apps.core.models import Shop
from apps.sources.models import DetectedBy, ProductSource


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t140-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t140-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
    )


def _profile(shop: Shop, **overrides) -> DeliveryProfile:
    data = {
        "source_app": "cj",
        "ship_from_country": "CN",
        "processing_days_min": 2,
        "processing_days_max": 4,
        "transit_days": {"NL": [6, 10], "DE": [7, 11]},
        "shipping_cost": {"NL": {"amount": "4.95", "free_from": "40.00"}},
    }
    data.update(overrides)
    return DeliveryProfile.objects.create(shop=shop, **data)


def _source(shop: Shop, product_gid: str, source: str = "cj") -> ProductSource:
    return ProductSource.objects.create(
        shop=shop,
        product_gid=product_gid,
        source=source,
        detected_by=DetectedBy.MERCHANT,
    )


class TestDeliveryProfileModel:
    def test_create_valid(self, db, shop):
        p = _profile(shop)
        p.full_clean()
        assert p.ship_from_country == "CN"

    def test_unique_per_shop_source_app(self, db, shop):
        _profile(shop)
        import django.db

        with pytest.raises(django.db.IntegrityError):
            _profile(shop, ship_from_country="US")

    def test_validation_max_15(self, db, shop):
        from django.core.exceptions import ValidationError

        p = _profile(shop, processing_days_max=16)
        with pytest.raises(ValidationError):
            p.full_clean()

    def test_validation_min_le_max(self, db, shop):
        from django.core.exceptions import ValidationError

        p = _profile(shop, processing_days_min=5, processing_days_max=3)
        with pytest.raises(ValidationError):
            p.full_clean()

    def test_validation_transit_per_market_min_le_max(self, db, shop):
        from django.core.exceptions import ValidationError

        p = _profile(shop, transit_days={"NL": [10, 4]})
        with pytest.raises(ValidationError):
            p.full_clean()

    def test_validation_unknown_source_app(self, db, shop):
        from django.core.exceptions import ValidationError

        p = _profile(shop, source_app="bogus")
        with pytest.raises(ValidationError):
            p.full_clean()


class TestDeliveryOverride:
    def test_fallback_to_profile_fields(self, db, shop):
        """Null override fields fall back to the profile."""
        _profile(shop)
        gid = "gid://shopify/Product/111"
        _source(shop, gid)
        DeliveryOverride.objects.create(
            shop=shop, product_gid=gid, transit_days={"NL": [3, 5]}
        )
        est = estimate(shop, gid, "NL")
        assert est is not None
        # processing from profile (2-4) + override transit (3-5) = 5-9
        assert est.min_days == 5
        assert est.max_days == 9
        assert est.ship_from == "CN"
        assert est.source == "override"

    def test_unique_per_shop_product(self, db, shop):
        gid = "gid://shopify/Product/222"
        _profile(shop)
        DeliveryOverride.objects.create(shop=shop, product_gid=gid)
        import django.db

        with pytest.raises(django.db.IntegrityError):
            DeliveryOverride.objects.create(shop=shop, product_gid=gid)


class TestEstimate:
    def test_profile_estimate(self, db, shop):
        """Profile CJ (CN, 2-4 processing, NL transit 6-10) -> NL 8-14, CN."""
        _profile(shop)
        gid = "gid://shopify/Product/999"
        _source(shop, gid)
        est = estimate(shop, gid, "NL")
        assert est is not None
        assert est.min_days == 8
        assert est.max_days == 14
        assert est.ship_from == "CN"
        assert est.source == "profile"

    def test_returns_none_without_profile(self, db, shop):
        assert estimate(shop, "gid://shopify/Product/000", "NL") is None

    def test_returns_none_without_transit_for_market(self, db, shop):
        _profile(shop, transit_days={"DE": [7, 11]})
        assert estimate(shop, "gid://shopify/Product/000", "NL") is None

    def test_no_over_30_flag_for_cj(self, db, shop):
        _profile(shop)
        gid = "gid://shopify/Product/999"
        _source(shop, gid)
        est = estimate(shop, gid, "NL")
        assert est.over_30_days is False

    def test_over_30_flag_when_max_exceeds(self, db, shop):
        _profile(shop, transit_days={"NL": [28, 35]})
        gid = "gid://shopify/Product/999"
        _source(shop, gid)
        est = estimate(shop, gid, "NL")
        assert est.max_days == 39
        assert est.over_30_days is True

    def test_shipping_cost_from_profile(self, db, shop):
        _profile(shop)
        gid = "gid://shopify/Product/999"
        _source(shop, gid)
        est = estimate(shop, gid, "NL")
        assert est.shipping_cost == Decimal("4.95")
        assert est.free_from == Decimal("40.00")

    def test_override_without_profile_returns_none(self, db, shop):
        """Override alone (no profile) still provides the estimate fields."""
        gid = "gid://shopify/Product/555"
        DeliveryOverride.objects.create(
            shop=shop,
            product_gid=gid,
            ship_from_country="DE",
            processing_days_min=1,
            processing_days_max=2,
            transit_days={"NL": [2, 3]},
        )
        est = estimate(shop, gid, "NL")
        assert est is not None
        assert est.min_days == 3
        assert est.max_days == 5
        assert est.ship_from == "DE"
        assert est.source == "override"
