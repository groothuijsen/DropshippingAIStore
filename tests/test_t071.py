"""Tests for T-071: Offer model + editor + activate/deactivate."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.offers.editor import (
    MAX_ACTIVE_MOSAIQ_DISCOUNTS,
    activate_offer,
    check_activation_limits,
    create_offer,
    deactivate_offer,
    expire_offer,
    validate_offer_config,
)
from apps.offers.models import Offer, OfferKind, OfferStatus


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
def valid_volume_config():
    return {
        "offer_id": "offer-1",
        "kind": "volume",
        "product_ids": ["gid://shopify/Product/1"],
        "tiers": [
            {"min_qty": 2, "type": "percentage", "value": "10.0"},
            {"min_qty": 3, "type": "percentage", "value": "15.0"},
        ],
        "labels": {"nl": "Koop 2+, bespaar 10%", "en": "Buy 2+, save 10%", "de": "Kaufen 2+, spare 10%"},
    }


@pytest.fixture
def valid_bogo_config():
    return {
        "offer_id": "offer-2",
        "kind": "bogo",
        "product_ids": ["gid://shopify/Product/1"],
        "bogo": {"buy_qty": 1, "get_qty": 1, "get_percentage": "100.0"},
        "labels": {"nl": "1+1 gratis", "en": "1+1 free", "de": "1+1 gratis"},
    }


class TestOfferModel:
    def test_create_offer(self, db, shop):
        offer = Offer.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="Test Offer",
            kind=OfferKind.VOLUME,
            config={
                "offer_id": "o1",
                "kind": "volume",
                "product_ids": ["x"],
                "labels": {"nl": "a", "en": "b", "de": "c"},
            },
        )
        assert offer.status == OfferStatus.DRAFT
        assert offer.show_timer is False
        assert offer.timer_active is False

    def test_clean_show_timer_without_ends_at_fails(self, shop):
        offer = Offer(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="T",
            kind=OfferKind.VOLUME,
            config={},
            show_timer=True,
            ends_at=None,
        )
        with pytest.raises(ValidationError, match="Cannot enable timer"):
            offer.clean()

    def test_clean_ends_at_too_far_future_fails(self, shop):
        offer = Offer(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="T",
            kind=OfferKind.VOLUME,
            config={},
            show_timer=True,
            ends_at=timezone.now() + timedelta(days=91),
        )
        with pytest.raises(ValidationError, match="90 days"):
            offer.clean()

    def test_clean_valid_timer(self, shop):
        offer = Offer(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="T",
            kind=OfferKind.VOLUME,
            config={},
            show_timer=True,
            ends_at=timezone.now() + timedelta(days=7),
        )
        offer.clean()  # Should not raise

    def test_db_constraint_timer_requires_ends_at(self, shop):
        """DB CheckConstraint: show_timer=True without ends_at is rejected."""
        from django.db import IntegrityError

        offer = Offer(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="T",
            kind=OfferKind.VOLUME,
            config={},
            show_timer=True,
            ends_at=None,
        )
        # clean() catches it first
        with pytest.raises(ValidationError):
            offer.clean()
        # Bypass clean() to test DB constraint directly
        with pytest.raises(IntegrityError):
            Offer.objects.bulk_create([offer])

    def test_timer_active_property(self, shop):
        offer = Offer(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="T",
            kind=OfferKind.VOLUME,
            config={},
            show_timer=True,
            ends_at=timezone.now() + timedelta(hours=1),
        )
        assert offer.timer_active is True

    def test_timer_active_expired(self, shop):
        offer = Offer(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="T",
            kind=OfferKind.VOLUME,
            config={},
            show_timer=True,
            ends_at=timezone.now() - timedelta(hours=1),
        )
        assert offer.timer_active is False
        assert offer.is_expired is True


class TestOfferEditor:
    def test_validate_volume_config_valid(self, valid_volume_config):
        valid, msg = validate_offer_config(valid_volume_config)
        assert valid is True

    def test_validate_volume_config_ascending_tiers(self):
        config = {
            "offer_id": "o1",
            "kind": "volume",
            "product_ids": ["x"],
            "tiers": [
                {"min_qty": 3, "type": "percentage", "value": "10.0"},
                {"min_qty": 2, "type": "percentage", "value": "15.0"},
            ],
            "labels": {"nl": "a", "en": "b", "de": "c"},
        }
        valid, msg = validate_offer_config(config)
        assert valid is False
        assert "ascending" in msg

    def test_validate_volume_config_percentage_too_high(self):
        config = {
            "offer_id": "o1",
            "kind": "volume",
            "product_ids": ["x"],
            "tiers": [
                {"min_qty": 2, "type": "percentage", "value": "71.0"},
                {"min_qty": 3, "type": "percentage", "value": "80.0"},
            ],
            "labels": {"nl": "a", "en": "b", "de": "c"},
        }
        valid, msg = validate_offer_config(config)
        assert valid is False

    def test_validate_volume_config_2_tiers_minimum(self, valid_volume_config):
        valid, _ = validate_offer_config(valid_volume_config)
        assert valid is True
        # 1 tier should fail
        config = dict(valid_volume_config)
        config["tiers"] = [{"min_qty": 2, "type": "percentage", "value": "10.0"}]
        valid, _ = validate_offer_config(config)
        assert valid is False

    def test_create_offer_success(self, shop, valid_volume_config):
        ok, msg, offer = create_offer(
            shop,
            "gid://shopify/Product/1",
            "Volume Offer",
            "volume",
            valid_volume_config,
        )
        assert ok is True
        assert offer.status == OfferStatus.DRAFT

    def test_create_offer_invalid_config(self, shop):
        bad_config = {
            "offer_id": "o1",
            "kind": "volume",
            "product_ids": ["x"],
            "tiers": [],
            "labels": {"nl": "a", "en": "b", "de": "c"},
        }
        ok, msg, offer = create_offer(shop, "gid://shopify/Product/1", "Bad", "volume", bad_config)
        assert ok is False
        assert offer is None

    def test_check_activation_limits(self, shop):
        allowed, msg = check_activation_limits(shop)
        assert allowed is True

    def test_check_activation_limits_max(self, shop):
        for i in range(MAX_ACTIVE_MOSAIQ_DISCOUNTS):
            Offer.objects.create(
                shop=shop,
                product_gid=f"gid://shopify/Product/{i}",
                title=f"Offer {i}",
                kind=OfferKind.VOLUME,
                config={},
                status=OfferStatus.ACTIVE,
            )
        allowed, msg = check_activation_limits(shop)
        assert allowed is False
        assert "20" in msg

    @patch("apps.core.shopify_client.load_query")
    @patch("apps.core.shopify_client.ShopifyGraphQLClient")
    @patch("apps.core.crypto.decrypt_token", return_value="test-token")
    def test_activate_offer_success(self, mock_decrypt, mock_client_class, mock_load_query, shop, valid_volume_config):
        _, _, offer = create_offer(shop, "gid://shopify/Product/1", "Test", "volume", valid_volume_config)

        # Mock the GraphQL client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.execute.side_effect = [
            {
                "discountAutomaticAppCreate": {
                    "automaticAppDiscount": {"id": "gid://shopify/Discount/1"},
                    "userErrors": [],
                }
            },
            {"metaobjectUpsert": {"metaobject": {"id": "gid://shopify/Metaobject/1"}, "userErrors": []}},
            {"metafieldsSet": {"metafields": [], "userErrors": []}},
        ]

        ok, msg = activate_offer(offer)
        assert ok is True
        offer.refresh_from_db()
        assert offer.status == OfferStatus.ACTIVE
        assert offer.discount_gid == "gid://shopify/Discount/1"

    @patch("apps.core.shopify_client.load_query")
    @patch("apps.core.shopify_client.ShopifyGraphQLClient")
    @patch("apps.core.crypto.decrypt_token", return_value="test-token")
    def test_activate_offer_already_active(
        self, mock_decrypt, mock_client_class, mock_load_query, shop, valid_volume_config
    ):
        _, _, offer = create_offer(shop, "gid://shopify/Product/1", "Test", "volume", valid_volume_config)

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.execute.side_effect = [
            {
                "discountAutomaticAppCreate": {
                    "automaticAppDiscount": {"id": "gid://shopify/Discount/1"},
                    "userErrors": [],
                }
            },
            {"metaobjectUpsert": {"metaobject": {"id": "gid://shopify/Metaobject/1"}, "userErrors": []}},
            {"metafieldsSet": {"metafields": [], "userErrors": []}},
        ]

        activate_offer(offer)
        ok, msg = activate_offer(offer)  # Second activation
        assert ok is True
        assert "Already" in msg

    @patch("apps.core.shopify_client.load_query")
    @patch("apps.core.shopify_client.ShopifyGraphQLClient")
    @patch("apps.core.crypto.decrypt_token", return_value="test-token")
    def test_deactivate_offer_success(
        self, mock_decrypt, mock_client_class, mock_load_query, shop, valid_volume_config
    ):
        _, _, offer = create_offer(shop, "gid://shopify/Product/1", "Test", "volume", valid_volume_config)

        # Mock activation
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.execute.side_effect = [
            {
                "discountAutomaticAppCreate": {
                    "automaticAppDiscount": {"id": "gid://shopify/Discount/1"},
                    "userErrors": [],
                }
            },
            {"metaobjectUpsert": {"metaobject": {"id": "gid://shopify/Metaobject/1"}, "userErrors": []}},
            {"metafieldsSet": {"metafields": [], "userErrors": []}},
        ]
        activate_offer(offer)

        # Mock deactivation
        mock_client.execute.side_effect = [
            {
                "discountAutomaticAppDelete": {
                    "deletedAutomaticAppDiscountId": "gid://shopify/Discount/1",
                    "userErrors": [],
                }
            },
            {"metaobjectDelete": {"deletedId": "gid://shopify/Metaobject/1", "userErrors": []}},
            {"metafieldsDelete": {"deletedMetafields": [], "userErrors": []}},
        ]

        ok, msg = deactivate_offer(offer)
        assert ok is True
        offer.refresh_from_db()
        assert offer.status == OfferStatus.DRAFT
        assert offer.discount_gid == ""

    def test_deactivate_offer_draft(self, shop, valid_volume_config):
        _, _, offer = create_offer(shop, "gid://shopify/Product/1", "Test", "volume", valid_volume_config)
        ok, msg = deactivate_offer(offer)
        assert ok is True
        assert "Already" in msg

    @patch("apps.core.shopify_client.load_query")
    @patch("apps.core.shopify_client.ShopifyGraphQLClient")
    @patch("apps.core.crypto.decrypt_token", return_value="test-token")
    def test_expire_offer(self, mock_decrypt, mock_client_class, mock_load_query, shop, valid_volume_config):
        _, _, offer = create_offer(shop, "gid://shopify/Product/1", "Test", "volume", valid_volume_config)

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.execute.side_effect = [
            {
                "discountAutomaticAppCreate": {
                    "automaticAppDiscount": {"id": "gid://shopify/Discount/1"},
                    "userErrors": [],
                }
            },
            {"metaobjectUpsert": {"metaobject": {"id": "gid://shopify/Metaobject/1"}, "userErrors": []}},
            {"metafieldsSet": {"metafields": [], "userErrors": []}},
        ]

        activate_offer(offer)
        # Set ends_at in the past
        offer.ends_at = timezone.now() - timedelta(hours=1)
        offer.show_timer = True
        offer.save(update_fields=["ends_at", "show_timer"])

        expire_offer(offer)
        offer.refresh_from_db()
        assert offer.status == OfferStatus.ENDED
