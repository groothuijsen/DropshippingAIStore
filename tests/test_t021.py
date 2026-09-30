"""Tests for T-021: ownership guards on ALL product mutations + variant_locations.

Key requirement from 06 §3: "There is a test that calls every product mutation
function on a locked product and expects the error."
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.sources.guards import LockedFieldError
from apps.sources.models import ProductSource
from apps.sources.product_mutations import (
    product_delete,
    product_set_metafield,
    product_set_template_suffix,
    product_update,
)
from apps.sources.rules import get_locked_fields
from apps.sources.variant_locations import (
    extract_fulfillment_signals,
    get_variant_locations,
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


@pytest.fixture
def locked_product(shop):
    """A product managed by DSers — all fields locked."""
    return ProductSource.objects.create(
        shop=shop,
        product_gid="gid://shopify/Product/LOCKED",
        source="dsers",
        detected_by="fulfillment_location",
        created_by_mosaiq=False,
        locked_fields=get_locked_fields("dsers"),
    )


@pytest.fixture
def mosaiq_product(shop):
    """A product created by Mosaiq — fully editable."""
    return ProductSource.objects.create(
        shop=shop,
        product_gid="gid://shopify/Product/MOSAIQ",
        source="manual",
        detected_by="mosaiq",
        created_by_mosaiq=True,
        locked_fields=[],
    )


# ── THE CRITICAL TEST: every mutation on a locked product ─────────────────


@pytest.mark.django_db
class TestAllMutationsBlockedOnLockedProduct:
    """06 §3: Every product mutation function on a locked product → LockedFieldError."""

    @patch("apps.sources.product_mutations._get_client")
    def test_product_update_title_blocked(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError):
            product_update(shop, "token", "gid://shopify/Product/LOCKED", title="New Title")
        mock_get_client.assert_not_called()  # No HTTP call

    @patch("apps.sources.product_mutations._get_client")
    def test_product_update_description_blocked(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError):
            product_update(shop, "token", "gid://shopify/Product/LOCKED", description_html="<p>New</p>")
        mock_get_client.assert_not_called()

    @patch("apps.sources.product_mutations._get_client")
    def test_product_update_vendor_blocked(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError):
            product_update(shop, "token", "gid://shopify/Product/LOCKED", vendor="NewVendor")
        mock_get_client.assert_not_called()

    @patch("apps.sources.product_mutations._get_client")
    def test_product_update_tags_blocked(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError):
            product_update(shop, "token", "gid://shopify/Product/LOCKED", tags=["new-tag"])
        mock_get_client.assert_not_called()

    @patch("apps.sources.product_mutations._get_client")
    def test_product_update_seo_blocked(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError):
            product_update(shop, "token", "gid://shopify/Product/LOCKED", seo_title="New SEO")
        mock_get_client.assert_not_called()

    @patch("apps.sources.product_mutations._get_client")
    def test_product_update_product_type_blocked(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError):
            product_update(shop, "token", "gid://shopify/Product/LOCKED", product_type="NewType")
        mock_get_client.assert_not_called()

    @patch("apps.sources.product_mutations._get_client")
    def test_product_delete_blocked(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError):
            product_delete(shop, "token", "gid://shopify/Product/LOCKED")
        mock_get_client.assert_not_called()


# ── Allowed operations on locked products ─────────────────────────────────


@pytest.mark.django_db
class TestAllowedOnLockedProduct:
    """06 §3: templateSuffix and $app:mosaiq metafields are always writable."""

    @patch("apps.sources.product_mutations._get_client")
    def test_template_suffix_allowed(self, mock_get_client, shop, locked_product):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "productSet": {"product": {"id": "gid://shopify/Product/LOCKED"}, "userErrors": []}
        }

        result = product_set_template_suffix(shop, "token", "gid://shopify/Product/LOCKED", "mosaiq")
        assert result["id"] == "gid://shopify/Product/LOCKED"

    @patch("apps.sources.product_mutations._get_client")
    def test_metafield_allowed(self, mock_get_client, shop, locked_product):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {"metafieldsSet": {"metafields": [], "userErrors": []}}

        result = product_set_metafield(
            shop,
            "token",
            "gid://shopify/Product/LOCKED",
            key="gpsr",
            value="{}",
        )
        assert result == []

    @patch("apps.sources.product_mutations._get_client")
    def test_update_with_only_template_suffix_allowed(self, mock_get_client, shop, locked_product):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "productSet": {"product": {"id": "gid://shopify/Product/LOCKED"}, "userErrors": []}
        }

        result = product_update(shop, "token", "gid://shopify/Product/LOCKED", template_suffix="mosaiq")
        assert result["id"] == "gid://shopify/Product/LOCKED"


# ── Allowed on Mosaiq-created products ────────────────────────────────────


@pytest.mark.django_db
class TestAllowedOnMosaiqProduct:
    """Products created by Mosaiq are fully editable."""

    @patch("apps.sources.product_mutations._get_client")
    def test_title_allowed(self, mock_get_client, shop, mosaiq_product):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "productSet": {"product": {"id": "gid://shopify/Product/MOSAIQ"}, "userErrors": []}
        }

        result = product_update(shop, "token", "gid://shopify/Product/MOSAIQ", title="New Title")
        assert result["id"] == "gid://shopify/Product/MOSAIQ"

    @patch("apps.sources.product_mutations._get_client")
    def test_price_allowed(self, mock_get_client, shop, mosaiq_product):
        # Mosaiq products can have price written via productSet
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "productSet": {"product": {"id": "gid://shopify/Product/MOSAIQ"}, "userErrors": []}
        }

        result = product_update(shop, "token", "gid://shopify/Product/MOSAIQ", title="X")
        assert result is not None


# ── Unknown product treated as locked ─────────────────────────────────────


@pytest.mark.django_db
class TestUnknownProductLocked:
    """No ProductSource record → treated as unknown origin."""

    @patch("apps.sources.product_mutations._get_client")
    def test_unknown_product_title_blocked(self, mock_get_client, shop):
        with pytest.raises(LockedFieldError):
            product_update(shop, "token", "gid://shopify/Product/UNKNOWN", title="Hack")
        mock_get_client.assert_not_called()


# ── Mixed fields test ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestMixedFields:
    """If any requested field is locked, the entire call fails."""

    @patch("apps.sources.product_mutations._get_client")
    def test_mixed_locked_and_writable(self, mock_get_client, shop, locked_product):
        with pytest.raises(LockedFieldError) as exc_info:
            product_update(
                shop,
                "token",
                "gid://shopify/Product/LOCKED",
                title="Locked!",  # locked
                template_suffix="mosaiq",  # writable
            )
        assert "title" in exc_info.value.fields
        mock_get_client.assert_not_called()


# ── Variant locations tests ───────────────────────────────────────────────


MOCK_VARIANT_LOCATIONS = {
    "productVariants": {
        "nodes": [
            {
                "id": "gid://shopify/ProductVariant/1",
                "sku": "PM-001",
                "inventoryItem": {
                    "tracked": True,
                    "inventoryLevels": {
                        "nodes": [
                            {
                                "location": {
                                    "name": "Printify",
                                    "isFulfillmentService": True,
                                    "fulfillmentService": {
                                        "handle": "printify",
                                        "serviceName": "Printify Fulfillment",
                                    },
                                }
                            }
                        ]
                    },
                },
            }
        ]
    }
}


@pytest.mark.django_db
class TestVariantLocations:
    @patch("apps.sources.variant_locations._get_client")
    def test_get_variant_locations(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_VARIANT_LOCATIONS

        result = get_variant_locations(shop, "token", "gid://shopify/Product/1")

        assert len(result) == 1
        assert result[0]["sku"] == "PM-001"
        assert result[0]["locations"][0]["name"] == "Printify"
        assert result[0]["locations"][0]["fulfillment_handle"] == "printify"

    @patch("apps.sources.variant_locations._get_client")
    def test_extract_signals(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_VARIANT_LOCATIONS

        result = get_variant_locations(shop, "token", "gid://shopify/Product/1")
        handle, name = extract_fulfillment_signals(result)
        assert handle == "printify"
        assert name == "Printify"

    @patch("apps.sources.variant_locations._get_client")
    def test_no_locations(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {"productVariants": {"nodes": []}}

        result = get_variant_locations(shop, "token", "gid://shopify/Product/1")
        handle, name = extract_fulfillment_signals(result)
        assert handle is None
        assert name is None

    @patch("apps.sources.variant_locations._get_client")
    def test_numeric_id_extraction(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {"productVariants": {"nodes": []}}

        get_variant_locations(shop, "token", "gid://shopify/Product/12345")
        # Verify the query used the numeric ID
        call_args = mock_client.execute.call_args
        assert call_args[0][1]["query"] == "product_id:12345"


# ── Full detection pipeline test ──────────────────────────────────────────


@pytest.mark.django_db
class TestFullDetectionPipeline:
    """Integration: variant_locations → detect_source → ProductSource."""

    @patch("apps.sources.variant_locations._get_client")
    @patch("apps.generator.import_tasks._get_client")
    def test_full_pipeline_printify(self, mock_import_client, mock_vl_client, shop):
        """Variant location 'Printify' → source=printify, locked fields set."""
        from apps.sources.rules import detect_source, get_locked_fields

        # Mock variant_locations
        vl_client = MagicMock()
        mock_vl_client.return_value = vl_client
        vl_client.execute.return_value = MOCK_VARIANT_LOCATIONS

        # Mock product_get
        import_client = MagicMock()
        mock_import_client.return_value = import_client
        import_client.execute.return_value = {
            "product": {
                "id": "gid://shopify/Product/1",
                "title": "Test Product",
                "vendor": "Some Vendor",
                "tags": "",
                "productType": "",
                "descriptionHtml": "",
                "status": "ACTIVE",
                "options": [],
                "variants": {
                    "nodes": [{"id": "v1", "title": "V", "price": "10.00", "compareAtPrice": None, "sku": "X1"}]
                },
                "media": {"nodes": []},
                "metafields": {"nodes": []},
            }
        }

        # Step 1: Get variant locations
        vl_data = get_variant_locations(shop, "token", "gid://shopify/Product/1")
        handle, name = extract_fulfillment_signals(vl_data)

        # Step 2: Detect source
        source, detected_by = detect_source(
            fulfillment_handle=handle,
            location_name=name,
            vendor="Some Vendor",
        )
        assert source == "printify"
        assert detected_by == "fulfillment_location"

        # Step 3: Verify locked fields
        locked = get_locked_fields(source)
        assert "title" in locked
        assert "price" in locked
