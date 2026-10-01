"""Tests for T-006: installation tasks, metaobject/metafield definitions, shop population."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.installation import (
    ensure_metafield_definitions,
    ensure_metaobject_definitions,
    on_install,
    populate_shop_from_info,
    write_default_shop_metafields,
)
from apps.core.models import AuditLog, Shop, ShopStatus
from apps.core.shopify_client import load_query
from apps.core.tasks import run_on_install

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def shop(db):
    """Create a test shop with encrypted tokens."""
    now = timezone.now()
    return Shop.objects.create(
        domain="test-store.myshopify.com",
        shopify_gid="gid://shopify/Shop/123",
        access_token_encrypted=encrypt_token("shpat_test_access_token_12345"),
        access_token_expires_at=now + timedelta(hours=1),
        refresh_token_encrypted=encrypt_token("shpat_test_refresh_token_67890"),
        refresh_token_expires_at=now + timedelta(days=90),
        name="Test Store",
        email="merchant@example.com",
        currency_code="EUR",
        iana_timezone="Europe/Amsterdam",
        status=ShopStatus.ACTIVE,
    )


MOCK_SHOP_INFO_RESPONSE = {
    "shop": {
        "id": "gid://shopify/Shop/123",
        "name": "Test Store",
        "email": "merchant@example.com",
        "currencyCode": "EUR",
        "ianaTimezone": "Europe/Amsterdam",
        "primaryDomain": {"url": "https://test-store.myshopify.com"},
        "billingAddress": {"countryCodeV2": "NL"},
    },
    "shopLocales": [
        {"locale": "nl", "primary": True, "published": True},
        {"locale": "en", "primary": False, "published": True},
        {"locale": "de", "primary": False, "published": False},
    ],
}

MOCK_INSTALLATION_RESPONSE = {
    "currentAppInstallation": {
        "id": "gid://shopify/AppInstallation/456",
        "activeSubscriptions": [],
    }
}

MOCK_PAGE_CONTENT_DEF = {
    "metaobjectDefinitionByType": {
        "id": "gid://shopify/MetaobjectDefinition/1",
        "type": "$app:page_content",
        "fieldDefinitions": [],
    }
}

MOCK_OFFER_DISPLAY_DEF = {
    "metaobjectDefinitionByType": {
        "id": "gid://shopify/MetaobjectDefinition/2",
        "type": "$app:offer_display",
        "fieldDefinitions": [],
    }
}

MOCK_NOT_FOUND = {"metaobjectDefinitionByType": None}

MOCK_METAFIELDS_SET_RESPONSE = {
    "metafieldsSet": {
        "metafields": [
            {"id": "gid://shopify/Metafield/1", "namespace": "$app:mosaiq", "key": "design_tokens", "value": "{}"},
        ],
        "userErrors": [],
    }
}

MOCK_EMPTY_DEFS = {"metafieldDefinitions": {"nodes": []}}


# ── GraphQL loader tests ──────────────────────────────────────────────────


class TestGraphqlLoader:
    def test_load_metaobject_definition_by_type(self):
        q = load_query("metaobject_definition_by_type")
        assert "metaobjectDefinitionByType" in q

    def test_load_metaobject_definition_create(self):
        q = load_query("metaobject_definition_create")
        assert "metaobjectDefinitionCreate" in q

    def test_load_metafield_definitions_by_owner(self):
        q = load_query("metafield_definitions_by_owner")
        assert "metafieldDefinitions" in q

    def test_load_metafield_definition_create(self):
        q = load_query("metafield_definition_create")
        assert "metafieldDefinitionCreate" in q

    def test_load_metafields_set(self):
        q = load_query("metafields_set")
        assert "metafieldsSet" in q

    def test_load_bulk_operation_run_query(self):
        q = load_query("bulk_operation_run_query")
        assert "bulkOperationRunQuery" in q

    def test_load_current_bulk_operation(self):
        q = load_query("current_bulk_operation")
        assert "currentBulkOperation" in q

    def test_load_products_variants(self):
        q = load_query("products_variants")
        assert "variants" in q


# ── Shop model tests ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestShopModel:
    def test_installation_id_field(self, shop):
        """Shop model has an installation_id field."""
        assert hasattr(shop, "installation_id")
        shop.installation_id = "gid://shopify/AppInstallation/456"
        shop.save(update_fields=["installation_id"])
        shop.refresh_from_db()
        assert shop.installation_id == "gid://shopify/AppInstallation/456"


# ── populate_shop_from_info tests ─────────────────────────────────────────


@pytest.mark.django_db
class TestPopulateShopFromInfo:
    def test_creates_new_shop(self):
        """A new shop is created from shop_info response."""
        shop = populate_shop_from_info(
            MOCK_SHOP_INFO_RESPONSE,
            domain="test-store.myshopify.com",
        )

        assert shop is not None
        assert shop.domain == "test-store.myshopify.com"
        assert shop.shopify_gid == "gid://shopify/Shop/123"
        assert shop.name == "Test Store"
        assert shop.email == "merchant@example.com"
        assert shop.currency_code == "EUR"
        assert shop.iana_timezone == "Europe/Amsterdam"
        assert shop.country_code == "NL"
        assert shop.primary_locale == "nl"

    def test_updates_existing_shop(self):
        """An existing shop is updated, not duplicated."""
        existing = Shop.objects.create(
            domain="test-store.myshopify.com",
            shopify_gid="gid://shopify/Shop/123",
            access_token_encrypted=encrypt_token("old_token"),
            refresh_token_encrypted=encrypt_token("old_refresh"),
            name="Old Name",
            status="active",
        )

        updated_info = {
            "shop": {
                **MOCK_SHOP_INFO_RESPONSE["shop"],
                "name": "New Store Name",
            },
            "shopLocales": MOCK_SHOP_INFO_RESPONSE["shopLocales"],
        }

        shop = populate_shop_from_info(
            updated_info,
            domain="test-store.myshopify.com",
        )

        assert shop.id == existing.id  # Same shop, not a new one
        assert shop.name == "New Store Name"

    def test_primary_locale_detection(self):
        """Primary locale is correctly detected from shopLocales."""
        info = {
            "shop": MOCK_SHOP_INFO_RESPONSE["shop"],
            "shopLocales": [
                {"locale": "en", "primary": False, "published": True},
                {"locale": "de", "primary": True, "published": True},
            ],
        }
        shop = populate_shop_from_info(info, domain="de-store.myshopify.com")
        assert shop.primary_locale == "de"

    def test_missing_billing_address(self):
        """Gracefully handles missing billing address."""
        info = {
            "shop": {
                **MOCK_SHOP_INFO_RESPONSE["shop"],
                "billingAddress": None,
            },
            "shopLocales": [],
        }
        shop = populate_shop_from_info(info, domain="no-billing.myshopify.com")
        assert shop.country_code == ""


# ── ensure_metaobject_definitions tests ───────────────────────────────────


class TestEnsureMetaobjectDefinitions:
    @patch("apps.core.installation._get_client")
    def test_skips_when_both_exist(self, mock_get_client):
        """No creation calls if both definitions already exist."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [MOCK_PAGE_CONTENT_DEF, MOCK_OFFER_DISPLAY_DEF]

        result = ensure_metaobject_definitions("test.myshopify.com", "token123")

        assert result == {"$app:page_content": "exists", "$app:offer_display": "exists"}
        assert mock_client.execute.call_count == 2

    @patch("apps.core.installation._get_client")
    def test_creates_when_missing(self, mock_get_client):
        """Creates definition when not found."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.execute.side_effect = [
            MOCK_NOT_FOUND,  # check page_content
            {
                "metaobjectDefinitionCreate": {
                    "metaobjectDefinition": {"id": "gid://shopify/MetaobjectDefinition/10"},
                    "userErrors": [],
                }
            },
            MOCK_NOT_FOUND,  # check offer_display
            {
                "metaobjectDefinitionCreate": {
                    "metaobjectDefinition": {"id": "gid://shopify/MetaobjectDefinition/11"},
                    "userErrors": [],
                }
            },
        ]

        result = ensure_metaobject_definitions("test.myshopify.com", "token123")

        assert result == {"$app:page_content": "created", "$app:offer_display": "created"}
        assert mock_client.execute.call_count == 4

    @patch("apps.core.installation._get_client")
    def test_handles_create_error(self, mock_get_client):
        """Handles user errors during creation."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.execute.side_effect = [
            MOCK_NOT_FOUND,
            {
                "metaobjectDefinitionCreate": {
                    "metaobjectDefinition": None,
                    "userErrors": [{"message": "Type already exists"}],
                }
            },
            MOCK_OFFER_DISPLAY_DEF,
        ]

        result = ensure_metaobject_definitions("test.myshopify.com", "token123")

        assert result["$app:page_content"] == "error"
        assert result["$app:offer_display"] == "exists"


# ── ensure_metafield_definitions tests ────────────────────────────────────


class TestEnsureMetafieldDefinitions:
    @patch("apps.core.installation._get_client")
    def test_creates_missing_definitions(self, mock_get_client):
        """Missing definitions are created."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # All owner types return empty
        mock_client.execute.return_value = MOCK_EMPTY_DEFS

        result = ensure_metafield_definitions("test.myshopify.com", "token123")

        # All definitions should be 'created'
        for key, status in result.items():
            assert status == "created", f"{key} should be 'created' but was '{status}'"

    @patch("apps.core.installation._get_client")
    def test_skips_existing_definitions(self, mock_get_client):
        """Existing definitions are not re-created."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # PRODUCT already has 'page'
        mock_client.execute.return_value = {
            "metafieldDefinitions": {
                "nodes": [
                    {"key": "page", "type": {"name": "list.metaobject_reference"}},
                ]
            }
        }

        result = ensure_metafield_definitions("test.myshopify.com", "token123")

        assert result.get("PRODUCT:page") == "exists"


# ── write_default_shop_metafields tests ───────────────────────────────────


class TestWriteDefaultShopMetafields:
    @patch("apps.core.installation._get_client")
    def test_writes_all_default_metafields(self, mock_get_client):
        """All four shop metafields are written with defaults."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_METAFIELDS_SET_RESPONSE

        shop = MagicMock()
        shop.domain = "test.myshopify.com"
        shop.id = "gid://shopify/Shop/123"

        result = write_default_shop_metafields(shop, "token123")

        assert result is True
        assert mock_client.execute.call_count >= 1

        # Verify the metafields input contains all 4 keys
        call_args = mock_client.execute.call_args_list[0]
        metafields = call_args[0][1]["metafields"]
        keys = {m["key"] for m in metafields}
        assert keys == {"design_tokens", "withdrawal", "settings", "cart"}

    @patch("apps.core.installation._get_client")
    def test_handles_user_errors(self, mock_get_client):
        """User errors in metafieldsSet are logged but don't crash."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "metafieldsSet": {
                "metafields": [],
                "userErrors": [{"field": "metafields", "message": "Invalid value", "code": "INVALID"}],
            }
        }

        shop = MagicMock()
        shop.domain = "test.myshopify.com"
        shop.id = "gid://shopify/Shop/123"

        result = write_default_shop_metafields(shop, "token123")
        assert result is False


# ── on_install tests ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestOnInstall:
    @patch("apps.core.installation.write_default_shop_metafields")
    @patch("apps.core.installation.ensure_metafield_definitions")
    @patch("apps.core.installation.ensure_metaobject_definitions")
    @patch("apps.core.installation._get_client")
    def test_full_installation_flow(self, mock_get_client, mock_metaobj, mock_metafield, mock_write_meta):
        """Full installation: shop_info → installation → definitions → metafields."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [
            MOCK_SHOP_INFO_RESPONSE,
            MOCK_INSTALLATION_RESPONSE,
        ]

        mock_metaobj.return_value = {"$app:page_content": "created", "$app:offer_display": "created"}
        mock_metafield.return_value = {"PRODUCT:page": "created"}
        mock_write_meta.return_value = True

        shop = on_install("test-store.myshopify.com", "access_token_123")

        assert shop is not None
        assert shop.domain == "test-store.myshopify.com"
        assert shop.installation_id == "gid://shopify/AppInstallation/456"
        assert mock_metaobj.called
        assert mock_metafield.called
        assert mock_write_meta.called

    @patch("apps.core.installation.write_default_shop_metafields")
    @patch("apps.core.installation.ensure_metafield_definitions")
    @patch("apps.core.installation.ensure_metaobject_definitions")
    @patch("apps.core.installation._get_client")
    def test_idempotent(self, mock_get_client, mock_metaobj, mock_metafield, mock_write_meta):
        """Running on_install twice does not create duplicate shops."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [
            MOCK_SHOP_INFO_RESPONSE,
            MOCK_INSTALLATION_RESPONSE,
            MOCK_SHOP_INFO_RESPONSE,
            MOCK_INSTALLATION_RESPONSE,
        ]
        mock_metaobj.return_value = {"$app:page_content": "exists", "$app:offer_display": "exists"}
        mock_metafield.return_value = {"PRODUCT:page": "exists"}
        mock_write_meta.return_value = True

        shop1 = on_install("test-store.myshopify.com", "access_token_123")
        shop2 = on_install("test-store.myshopify.com", "access_token_123")

        assert shop1.id == shop2.id  # Same shop, not duplicated

    @patch("apps.core.installation.write_default_shop_metafields")
    @patch("apps.core.installation.ensure_metafield_definitions")
    @patch("apps.core.installation.ensure_metaobject_definitions")
    @patch("apps.core.installation._get_client")
    def test_creates_audit_log(self, mock_get_client, mock_metaobj, mock_metafield, mock_write_meta):
        """Installation creates an AuditLog entry."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [
            MOCK_SHOP_INFO_RESPONSE,
            MOCK_INSTALLATION_RESPONSE,
        ]
        mock_metaobj.return_value = {"$app:page_content": "created"}
        mock_metafield.return_value = {"PRODUCT:page": "created"}
        mock_write_meta.return_value = True

        shop = on_install("test-store.myshopify.com", "access_token_123")

        log = AuditLog.objects.filter(shop=shop, action="installed").first()
        assert log is not None
        assert log.actor == "system"
        assert "metaobject_definitions" in log.payload
        assert "metafield_definitions" in log.payload


# ── run_on_install Celery task tests ──────────────────────────────────────


@pytest.mark.django_db
class TestRunOnInstallTask:
    @patch("apps.core.installation.on_install")
    def test_dispatches_installation(self, mock_on_install):
        """The Celery task calls on_install with decrypted token."""
        mock_on_install.return_value = MagicMock(domain="test.myshopify.com")

        shop = Shop.objects.create(
            domain="test.myshopify.com",
            shopify_gid="gid://shopify/Shop/999",
            access_token_encrypted=encrypt_token("shpat_test"),
            access_token_expires_at=timezone.now() + timedelta(hours=1),
            refresh_token_encrypted=encrypt_token("refresh_test"),
            refresh_token_expires_at=timezone.now() + timedelta(days=90),
        )

        result = run_on_install(str(shop.id))

        mock_on_install.assert_called_once_with("test.myshopify.com", "shpat_test")
        assert result["status"] == "completed"

    def test_handles_missing_shop(self):
        """Returns error when shop doesn't exist."""
        result = run_on_install("00000000-0000-0000-0000-000000000000")
        assert result["error"] == "shop_not_found"

    @patch("apps.core.installation.on_install")
    def test_handles_installation_error(self, mock_on_install):
        """Returns error when installation fails."""
        mock_on_install.side_effect = Exception("Shopify API error")

        shop = Shop.objects.create(
            domain="fail-store.myshopify.com",
            shopify_gid="gid://shopify/Shop/888",
            access_token_encrypted=encrypt_token("shpat_test"),
            access_token_expires_at=timezone.now() + timedelta(hours=1),
            refresh_token_encrypted=encrypt_token("refresh_test"),
            refresh_token_expires_at=timezone.now() + timedelta(days=90),
        )

        result = run_on_install(str(shop.id))
        assert "error" in result
        assert "Shopify API error" in result["error"]
