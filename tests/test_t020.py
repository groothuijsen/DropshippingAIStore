"""Tests for T-020: product import, source detection, guards, ImportResult."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.errors import ImportNotFound
from apps.generator.import_tasks import import_manual, import_product_gid
from apps.sources.guards import LockedFieldError, assert_writable
from apps.sources.models import ProductSource
from apps.sources.rules import (
    ALWAYS_LOCKED_FIELDS,
    ALWAYS_WRITABLE_FIELDS,
    SOURCE_RULES,
    detect_source,
    get_locked_fields,
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


MOCK_PRODUCT_RESPONSE = {
    "product": {
        "id": "gid://shopify/Product/1",
        "title": "Sleep Mask",
        "handle": "sleep-mask",
        "vendor": "Printify",
        "tags": "sleep, mask",
        "productType": "Accessories",
        "descriptionHtml": "<p>A premium sleep mask</p>",
        "status": "ACTIVE",
        "options": [{"name": "Color", "values": ["Black"]}],
        "variants": {
            "nodes": [
                {
                    "id": "gid://shopify/ProductVariant/1",
                    "title": "Default",
                    "price": "29.99",
                    "compareAtPrice": None,
                    "sku": "PM-001",
                }
            ]
        },
        "media": {
            "nodes": [
                {
                    "id": "gid://shopify/MediaImage/1",
                    "image": {"url": "https://cdn.example.com/img1.jpg", "altText": "Front"},
                },
                {
                    "id": "gid://shopify/MediaImage/2",
                    "image": {"url": "https://cdn.example.com/img2.jpg", "altText": "Back"},
                },
            ]
        },
        "metafields": {"nodes": []},
    }
}

MOCK_MANUAL_RESPONSE = {
    "productSet": {
        "product": {
            "id": "gid://shopify/Product/999",
            "title": "Manual Product",
            "handle": "manual-product",
            "status": "DRAFT",
        },
        "userErrors": [],
    }
}


# ── Source rules tests ────────────────────────────────────────────────────


class TestSourceRules:
    def test_rules_exist(self):
        assert len(SOURCE_RULES) > 0

    def test_always_locked_fields(self):
        assert "title" in ALWAYS_LOCKED_FIELDS
        assert "price" in ALWAYS_LOCKED_FIELDS
        assert "templateSuffix" in ALWAYS_WRITABLE_FIELDS

    def test_get_locked_fields_manual(self):
        assert get_locked_fields("manual") == []

    def test_get_locked_fields_dsers(self):
        locked = get_locked_fields("dsers")
        assert "title" in locked
        assert "price" in locked
        assert "templateSuffix" not in locked

    def test_get_locked_fields_unknown(self):
        locked = get_locked_fields("unknown_app")
        assert "title" in locked


class TestDetectSource:
    def test_dsers_by_fulfillment_handle(self):
        source, detected_by = detect_source(fulfillment_handle="dsers-fulfillment-service")
        assert source == "dsers"
        assert detected_by == "fulfillment_location"

    def test_printify_by_location_name(self):
        source, detected_by = detect_source(location_name="Printify")
        assert source == "printify"
        assert detected_by == "fulfillment_location"

    def test_printful_by_location_name(self):
        source, detected_by = detect_source(location_name="Printful")
        assert source == "printful"

    def test_autods_by_location_name(self):
        source, detected_by = detect_source(location_name="AutoDS Fulfillment")
        assert source == "autods"

    def test_zendrop_by_location_name(self):
        source, detected_by = detect_source(location_name="Zendrop US")
        assert source == "zendrop"

    def test_cj_by_location_name(self):
        source, detected_by = detect_source(location_name="CJ Dropshipping")
        assert source == "cj"

    def test_printify_by_vendor(self):
        source, detected_by = detect_source(vendor="Printify")
        assert source == "printify"
        assert detected_by == "vendor"

    def test_cj_by_sku_pattern(self):
        source, detected_by = detect_source(sku="CJ1234ABCD")
        assert source == "cj"
        assert detected_by == "sku"

    def test_onboarding_single_app(self):
        source, detected_by = detect_source(onboarding_apps=["dsers"])
        assert source == "dsers"
        assert detected_by == "onboarding"

    def test_onboarding_multiple_apps_unknown(self):
        source, detected_by = detect_source(onboarding_apps=["dsers", "printify"])
        assert source == "unknown_app"

    def test_no_signals_unknown(self):
        source, detected_by = detect_source()
        assert source == "unknown_app"

    def test_fulfillment_beats_vendor(self):
        """Fulfillment/location rules are strongest — checked before vendor."""
        source, _ = detect_source(
            fulfillment_handle="dsers-fulfillment-service",
            vendor="Some Other Vendor",
        )
        assert source == "dsers"


# ── Guards tests ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGuards:
    def test_writable_for_mosaiq_product(self, shop):
        ProductSource.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            source="manual",
            detected_by="mosaiq",
            created_by_mosaiq=True,
            locked_fields=[],
        )
        # Should not raise
        assert_writable(shop, "gid://shopify/Product/1", {"title", "price"})

    def test_locked_for_dsers_product(self, shop):
        ProductSource.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            source="dsers",
            detected_by="fulfillment_location",
            created_by_mosaiq=False,
            locked_fields=get_locked_fields("dsers"),
        )
        with pytest.raises(LockedFieldError) as exc_info:
            assert_writable(shop, "gid://shopify/Product/1", {"title", "price"})
        assert "title" in exc_info.value.fields
        assert "price" in exc_info.value.fields

    def test_template_suffix_always_writable(self, shop):
        ProductSource.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            source="dsers",
            detected_by="fulfillment_location",
            created_by_mosaiq=False,
            locked_fields=get_locked_fields("dsers"),
        )
        # Should not raise — templateSuffix is always writable
        assert_writable(shop, "gid://shopify/Product/1", {"templateSuffix"})

    def test_metafields_always_writable(self, shop):
        ProductSource.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            source="dsers",
            detected_by="fulfillment_location",
            created_by_mosaiq=False,
            locked_fields=get_locked_fields("dsers"),
        )
        assert_writable(shop, "gid://shopify/Product/1", {"$app:mosaiq"})

    def test_unknown_product_treated_as_locked(self, shop):
        """No ProductSource → treated as unknown origin, locked."""
        with pytest.raises(LockedFieldError):
            assert_writable(shop, "gid://shopify/Product/999", {"title"})

    def test_mixed_fields_some_locked(self, shop):
        ProductSource.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            source="dsers",
            detected_by="fulfillment_location",
            created_by_mosaiq=False,
            locked_fields=get_locked_fields("dsers"),
        )
        with pytest.raises(LockedFieldError) as exc_info:
            assert_writable(shop, "gid://shopify/Product/1", {"title", "templateSuffix"})
        assert exc_info.value.fields == ["title"]


# ── import_product_gid tests ──────────────────────────────────────────────


@pytest.mark.django_db
class TestImportProductGid:
    @patch("apps.generator.import_tasks._get_client")
    def test_imports_existing_product(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_PRODUCT_RESPONSE

        result = import_product_gid(shop, "token123", "gid://shopify/Product/1")

        assert result.product_gid == "gid://shopify/Product/1"
        assert result.title == "Sleep Mask"
        assert result.source_app == "printify"  # vendor = Printify
        assert result.price == Decimal("29.99")
        assert len(result.reference_image_urls) == 2

    @patch("apps.generator.import_tasks._get_client")
    def test_creates_product_source(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_PRODUCT_RESPONSE

        import_product_gid(shop, "token123", "gid://shopify/Product/1")

        ps = ProductSource.objects.get(shop=shop, product_gid="gid://shopify/Product/1")
        assert ps.source == "printify"
        assert ps.created_by_mosaiq is False
        assert "title" in ps.locked_fields

    @patch("apps.generator.import_tasks._get_client")
    def test_reuses_existing_product_source(self, mock_get_client, shop):
        ProductSource.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            source="manual",
            detected_by="mosaiq",
            created_by_mosaiq=True,
            locked_fields=[],
        )
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_PRODUCT_RESPONSE

        result = import_product_gid(shop, "token123", "gid://shopify/Product/1")
        assert result.source_app == "manual"
        assert ProductSource.objects.filter(shop=shop).count() == 1

    @patch("apps.generator.import_tasks._get_client")
    def test_product_not_found(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {"product": None}

        with pytest.raises(ImportNotFound):
            import_product_gid(shop, "token123", "gid://shopify/Product/999")


# ── import_manual tests ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestImportManual:
    @patch("apps.generator.import_tasks._get_client")
    def test_creates_manual_product(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_MANUAL_RESPONSE

        result = import_manual(
            shop,
            "token123",
            title="Manual Product",
            description="A great manual product description",
            price="19.99",
        )

        assert result.product_gid == "gid://shopify/Product/999"
        assert result.source_app == "manual"
        assert result.price == Decimal("19.99")

    @patch("apps.generator.import_tasks._get_client")
    def test_creates_product_source_manual(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_MANUAL_RESPONSE

        import_manual(shop, "token123", title="Manual Product", description="D" * 30)

        ps = ProductSource.objects.get(shop=shop, product_gid="gid://shopify/Product/999")
        assert ps.source == "manual"
        assert ps.created_by_mosaiq is True
        assert ps.detected_by == "mosaiq"
        assert ps.locked_fields == []

    @patch("apps.generator.import_tasks._get_client")
    def test_manual_product_fully_editable(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_MANUAL_RESPONSE

        result = import_manual(shop, "token123", title="MP", description="D" * 30)

        # Guards should allow writing to any field
        assert_writable(shop, result.product_gid, {"title", "price", "descriptionHtml"})

    @patch("apps.generator.import_tasks._get_client")
    def test_user_errors_raise(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "productSet": {"product": None, "userErrors": [{"field": "title", "message": "Required"}]}
        }

        with pytest.raises(RuntimeError, match="userErrors"):
            import_manual(shop, "token123", title="X", description="D" * 30)
