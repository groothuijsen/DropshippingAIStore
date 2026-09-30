"""Tests for T-087: store settings + metafield sync."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.core.store_settings import (
    STOCK_THRESHOLD_MAX,
    StoreSettings,
    save_settings,
    validate_settings,
)


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


# ── Validation tests ──────────────────────────────────────────────────────


class TestValidation:
    def test_valid_settings_pass(self):
        errors = validate_settings(
            guarantee_policy="2 jaar garantie",
            ship_cutoff={"time": "16:00", "days": ["mon", "tue"], "delivery_days": 1},
            ai_label_default=True,
            stock_threshold=5,
        )
        assert errors == []

    def test_stock_threshold_max(self):
        errors = validate_settings(
            guarantee_policy="",
            ship_cutoff=None,
            ai_label_default=True,
            stock_threshold=STOCK_THRESHOLD_MAX + 1,
        )
        assert any("stock_threshold" in e for e in errors)

    def test_stock_threshold_negative(self):
        errors = validate_settings(
            guarantee_policy="",
            ship_cutoff=None,
            ai_label_default=True,
            stock_threshold=-1,
        )
        assert any("non-negative" in e for e in errors)

    def test_invalid_ship_cutoff_days(self):
        errors = validate_settings(
            guarantee_policy="",
            ship_cutoff={"time": "16:00", "days": ["mon", "invalid"]},
            ai_label_default=True,
            stock_threshold=5,
        )
        assert any("invalid values" in e for e in errors)

    def test_negative_delivery_days(self):
        errors = validate_settings(
            guarantee_policy="",
            ship_cutoff={"delivery_days": -1},
            ai_label_default=True,
            stock_threshold=5,
        )
        assert any("delivery_days" in e for e in errors)

    def test_ship_cutoff_none_is_valid(self):
        errors = validate_settings(
            guarantee_policy="",
            ship_cutoff=None,
            ai_label_default=True,
            stock_threshold=5,
        )
        assert errors == []


# ── Save settings tests ───────────────────────────────────────────────────


class TestSaveSettings:
    @patch("apps.core.store_settings._sync_settings_metafield")
    def test_save_valid_settings(self, mock_sync, shop):
        errors = save_settings(
            shop,
            guarantee_policy="2 jaar garantie",
            ship_cutoff={"time": "16:00", "days": ["mon", "tue"]},
            ai_label_default=False,
            stock_threshold=8,
        )
        assert errors == []
        shop.refresh_from_db()
        assert shop.guarantee_policy == "2 jaar garantie"
        assert shop.ship_cutoff == {"time": "16:00", "days": ["mon", "tue"]}
        assert shop.ai_label_default is False
        assert shop.stock_threshold == 8
        mock_sync.assert_called_once()

    @patch("apps.core.store_settings._sync_settings_metafield")
    def test_save_invalid_settings_rejected(self, mock_sync, shop):
        errors = save_settings(
            shop,
            guarantee_policy="",
            ship_cutoff=None,
            ai_label_default=True,
            stock_threshold=STOCK_THRESHOLD_MAX + 1,
        )
        assert len(errors) > 0
        mock_sync.assert_not_called()

    @patch("apps.core.store_settings._sync_settings_metafield")
    def test_save_default_settings(self, mock_sync, shop):
        errors = save_settings(
            shop,
            guarantee_policy="",
            ship_cutoff=None,
            ai_label_default=True,
            stock_threshold=5,
        )
        assert errors == []
        shop.refresh_from_db()
        assert shop.guarantee_policy == ""
        assert shop.ship_cutoff is None
        assert shop.ai_label_default is True
        assert shop.stock_threshold == 5


# ── StoreSettings dataclass tests ─────────────────────────────────────────


class TestStoreSettings:
    def test_from_shop(self, shop):
        shop.guarantee_policy = "Test policy"
        shop.stock_threshold = 3
        shop.save(update_fields=["guarantee_policy", "stock_threshold"])

        settings = StoreSettings.from_shop(shop)
        assert settings.guarantee_policy == "Test policy"
        assert settings.stock_threshold == 3

    def test_to_metafield_value(self, shop):
        settings = StoreSettings(
            guarantee_policy="Test",
            ship_cutoff={"time": "16:00"},
            ai_label_default=False,
            stock_threshold=7,
        )
        value = settings.to_metafield_value()
        assert value["guarantee_policy"] == "Test"
        assert value["ship_cutoff"] == {"time": "16:00"}
        assert value["ai_label_default"] is False
        assert value["stock_threshold"] == 7


# ── Metafield sync tests ──────────────────────────────────────────────────


class TestMetafieldSync:
    @patch("apps.core.shopify_client.ShopifyGraphQLClient.execute")
    def test_sync_calls_graphql(self, mock_gql, shop):
        mock_gql.return_value = {"data": {"metafieldsSet": {"metafields": [], "userErrors": []}}}

        from apps.core.store_settings import _sync_settings_metafield

        _sync_settings_metafield(shop)
        mock_gql.assert_called_once()

    @patch("apps.core.shopify_client.ShopifyGraphQLClient.execute")
    def test_sync_handles_user_errors(self, mock_gql, shop):
        mock_gql.return_value = {
            "data": {"metafieldsSet": {"metafields": [], "userErrors": [{"field": ["value"], "message": "Invalid"}]}}
        }

        from apps.core.store_settings import _sync_settings_metafield

        # Should not raise
        _sync_settings_metafield(shop)

    @patch("apps.core.shopify_client.ShopifyGraphQLClient.execute")
    def test_sync_handles_exception(self, mock_gql, shop):
        mock_gql.side_effect = Exception("Network error")

        from apps.core.store_settings import _sync_settings_metafield

        # Should not raise
        _sync_settings_metafield(shop)
