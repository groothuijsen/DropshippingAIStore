"""Tests for delivery settings UI screens (F18-1..2, docs/12 §6).

- GET/POST /app/settings/delivery/  → delivery_profiles
- GET/POST /app/products/<gid>/delivery/ → delivery_override
"""

import json
from unittest.mock import patch

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.compliance.models import DeliveryOverride, DeliveryProfile
from apps.core.models import AuditLog, Shop
from apps.sources.models import DetectedBy, ProductSource


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t143-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t143-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        import_apps=["cj"],
    )


def _token(shop: Shop) -> str:
    return pyjwt.encode(
        {
            "iss": f"https://{shop.domain}/admin",
            "dest": f"https://{shop.domain}",
            "aud": settings.SHOPIFY_API_KEY,
            "sub": "12345",
            "exp": 9999999999,
            "nbf": 1000000000,
        },
        settings.SHOPIFY_API_SECRET,
        algorithm="HS256",
    )


def _url(shop: Shop) -> str:
    return f"/app/settings/delivery/?id_token={_token(shop)}"


class TestDeliveryProfilesScreen:
    def test_get_renders_rows(self, db, shop):
        DeliveryProfile.objects.create(
            shop=shop, source_app="cj", ship_from_country="CN",
            processing_days_min=2, processing_days_max=4,
            transit_days={"NL": [6, 10]}, shipping_cost={"NL": {"amount": "4.95"}},
        )
        resp = Client().get(_url(shop))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "cj" in content
        assert "CN" in content

    def test_get_shows_shop_source_apps(self, db, shop):
        """Rows cover Shop.import_apps plus manual (F18-1)."""
        resp = Client().get(_url(shop))
        content = resp.content.decode()
        assert "cj" in content
        assert "manual" in content

    @patch("apps.compliance.tasks.sync_delivery_metafields")
    def test_post_saves_profile(self, mock_sync, db, shop):
        resp = Client().post(
            _url(shop),
            data={
                "source_app": "cj",
                "ship_from_country": "CN",
                "processing_days_min": "2",
                "processing_days_max": "4",
                "transit_days": json.dumps({"NL": [6, 10]}),
                "shipping_cost": json.dumps({"NL": {"amount": "4.95", "free_from": "40.00"}}),
            },
        )
        assert resp.status_code == 302
        p = DeliveryProfile.objects.get(shop=shop, source_app="cj")
        assert p.ship_from_country == "CN"
        assert p.transit_days == {"NL": [6, 10]}
        assert p.shipping_cost["NL"]["amount"] == "4.95"
        assert AuditLog.objects.filter(shop=shop, action="delivery_profile_saved").exists()
        mock_sync.delay.assert_called_once_with(shop.domain)

    @patch("apps.compliance.tasks.sync_delivery_metafields")
    def test_post_invalid_json_shows_error(self, mock_sync, db, shop):
        resp = Client().post(
            _url(shop),
            data={
                "source_app": "cj",
                "ship_from_country": "CN",
                "processing_days_min": "2",
                "processing_days_max": "4",
                "transit_days": "not json",
            },
        )
        assert resp.status_code == 200
        assert DeliveryProfile.objects.filter(shop=shop).count() == 0
        mock_sync.delay.assert_not_called()

    @patch("apps.compliance.tasks.sync_delivery_metafields")
    def test_post_validation_error_rejected(self, mock_sync, db, shop):
        """min > max → error, nothing saved (12 §2.4 validation)."""
        resp = Client().post(
            _url(shop),
            data={
                "source_app": "cj",
                "ship_from_country": "CN",
                "processing_days_min": "10",
                "processing_days_max": "4",
                "transit_days": json.dumps({"NL": [6, 10]}),
            },
        )
        assert resp.status_code == 200
        assert DeliveryProfile.objects.filter(shop=shop).count() == 0
        mock_sync.delay.assert_not_called()

    @patch("apps.compliance.tasks.sync_delivery_metafields")
    def test_post_updates_existing(self, mock_sync, db, shop):
        DeliveryProfile.objects.create(
            shop=shop, source_app="cj", ship_from_country="CN",
            processing_days_min=2, processing_days_max=4,
            transit_days={"NL": [6, 10]},
        )
        Client().post(
            _url(shop),
            data={
                "source_app": "cj",
                "ship_from_country": "DE",
                "processing_days_min": "1",
                "processing_days_max": "2",
                "transit_days": json.dumps({"NL": [3, 5]}),
            },
        )
        p = DeliveryProfile.objects.get(shop=shop, source_app="cj")
        assert p.ship_from_country == "DE"
        assert DeliveryProfile.objects.filter(shop=shop).count() == 1
        mock_sync.delay.assert_called_once_with(shop.domain)


class TestDeliveryOverrideScreen:
    GID = "gid://shopify/Product/555"

    def _override_url(self, shop: Shop) -> str:
        from urllib.parse import quote

        return f"/app/products/{quote(self.GID, safe='')}/delivery/?id_token={_token(shop)}"

    @patch("apps.compliance.tasks.sync_delivery_metafields")
    def test_post_saves_override(self, mock_sync, db, shop):
        ProductSource.objects.create(
            shop=shop, product_gid=self.GID, source="cj", detected_by=DetectedBy.MERCHANT
        )
        resp = Client().post(
            self._override_url(shop),
            data={
                "transit_days": json.dumps({"NL": [3, 5]}),
            },
        )
        assert resp.status_code == 302
        o = DeliveryOverride.objects.get(shop=shop, product_gid=self.GID)
        assert o.transit_days == {"NL": [3, 5]}
        mock_sync.delay.assert_called_once_with(shop.domain)

    @patch("apps.compliance.tasks.sync_delivery_metafields")
    def test_post_clears_override_when_all_empty(self, mock_sync, db, shop):
        DeliveryOverride.objects.create(
            shop=shop, product_gid=self.GID, transit_days={"NL": [3, 5]}
        )
        resp = Client().post(
            self._override_url(shop),
            data={
                "transit_days": "",
                "ship_from_country": "",
                "processing_days_min": "",
                "processing_days_max": "",
            },
        )
        assert resp.status_code == 302
        assert DeliveryOverride.objects.filter(shop=shop, product_gid=self.GID).count() == 0
        mock_sync.delay.assert_called_once_with(shop.domain)

    def test_get_renders_existing_override(self, db, shop):
        DeliveryOverride.objects.create(
            shop=shop, product_gid=self.GID, transit_days={"NL": [3, 5]}
        )
        resp = Client().get(self._override_url(shop))
        assert resp.status_code == 200
        assert "NL" in resp.content.decode()

    @patch("apps.compliance.tasks.sync_delivery_metafields")
    def test_post_invalid_transit_json_shows_error(self, mock_sync, db, shop):
        resp = Client().post(
            self._override_url(shop),
            data={"transit_days": "{{{"},
        )
        assert resp.status_code == 200
        assert DeliveryOverride.objects.filter(shop=shop).count() == 0
        mock_sync.delay.assert_not_called()
