"""Tests for T-087: store settings."""

from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest
from django.test import Client
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.core.store_settings import (
    StoreSettings,
    save_settings,
    validate_settings,
)


def _make_token(shop_domain: str = "test-store.myshopify.com") -> str:
    """Generate a valid session token for middleware."""
    from django.conf import settings

    dest = f"https://{shop_domain}"
    payload = {
        "dest": dest,
        "iss": f"{dest}/admin",
        "aud": settings.SHOPIFY_API_KEY,
        "exp": (timezone.now() + timedelta(hours=1)).timestamp(),
    }
    return jwt.encode(payload, settings.SHOPIFY_API_SECRET, algorithm="HS256")


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


class TestStoreSettingsModel:
    def test_from_shop(self, shop):
        shop.guarantee_policy = "30-day money-back"
        shop.stock_threshold = 3
        shop.ai_label_default = False
        shop.ship_cutoff = {"time": "16:00", "days": ["mon", "tue"], "delivery_days": 1}
        shop.save()

        settings = StoreSettings.from_shop(shop)
        assert settings.guarantee_policy == "30-day money-back"
        assert settings.stock_threshold == 3
        assert settings.ai_label_default is False
        assert settings.ship_cutoff["time"] == "16:00"

    def test_to_metafield_value(self):
        s = StoreSettings(guarantee_policy="X", stock_threshold=5, ai_label_default=True)
        value = s.to_metafield_value()
        assert value["guarantee_policy"] == "X"
        assert value["stock_threshold"] == 5
        assert value["ai_label_default"] is True


class TestValidateSettings:
    def test_valid(self):
        errors = validate_settings("30-day", {"time": "16:00", "days": ["mon"], "delivery_days": 1}, True, 5)
        assert errors == []

    def test_stock_threshold_too_high(self):
        errors = validate_settings("", None, True, 11)
        assert any("at most 10" in e for e in errors)

    def test_stock_threshold_negative(self):
        errors = validate_settings("", None, True, -1)
        assert any("non-negative" in e for e in errors)

    def test_invalid_day(self):
        errors = validate_settings("", {"time": "16:00", "days": ["xyz"], "delivery_days": 1}, True, 5)
        assert any("invalid values" in e for e in errors)


class TestSaveSettings:
    @patch("apps.core.store_settings._sync_settings_metafield")
    def test_save(self, mock_sync, shop):
        errors = save_settings(
            shop,
            guarantee_policy="30-day money-back",
            ship_cutoff={"time": "16:00", "days": ["mon", "tue"], "delivery_days": 1},
            ai_label_default=False,
            stock_threshold=3,
        )
        assert errors == []
        shop.refresh_from_db()
        assert shop.guarantee_policy == "30-day money-back"
        assert shop.stock_threshold == 3
        assert shop.ai_label_default is False
        assert shop.ship_cutoff["time"] == "16:00"
        mock_sync.assert_called_once()

    @patch("apps.core.store_settings._sync_settings_metafield")
    def test_save_invalid(self, mock_sync, shop):
        errors = save_settings(shop, "", None, True, 11)
        assert len(errors) > 0
        mock_sync.assert_not_called()


class TestStoreSettingsView:
    def test_get_settings_page(self, shop):
        client = Client()
        token = _make_token(shop.domain)
        response = client.get(f"/app/settings/store/?id_token={token}")
        assert response.status_code == 200

    @patch("apps.core.store_settings._sync_settings_metafield")
    def test_post_settings(self, mock_sync, shop):
        client = Client()
        token = _make_token(shop.domain)
        response = client.post(
            f"/app/settings/store/?id_token={token}",
            {
                "guarantee_policy": "30-day money-back",
                "stock_threshold": "3",
                "ai_label_default": "on",
                "ship_cutoff_time": "16:00",
                "ship_cutoff_days": ["mon", "tue"],
                "delivery_days": "1",
            },
        )
        assert response.status_code == 302  # redirect after save
        shop.refresh_from_db()
        assert shop.guarantee_policy == "30-day money-back"
        assert shop.stock_threshold == 3

    @patch("apps.core.store_settings._sync_settings_metafield")
    def test_post_invalid_stock_threshold(self, mock_sync, shop):
        client = Client()
        token = _make_token(shop.domain)
        response = client.post(
            f"/app/settings/store/?id_token={token}",
            {
                "guarantee_policy": "",
                "stock_threshold": "99",
                "ai_label_default": "on",
            },
        )
        assert response.status_code == 200  # re-render with errors
        mock_sync.assert_not_called()
