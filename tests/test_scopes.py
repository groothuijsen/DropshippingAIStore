"""Tests for apps.core.scopes (T-110: scope check + re-grant screen, F15-2)."""

from unittest.mock import MagicMock, patch

import pytest

from apps.core.crypto import decrypt_token, encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.core.scopes import (
    REQUIRED_START_SCOPES,
    build_regrant_url,
    check_start_scopes,
    get_granted_scopes,
    missing_scopes,
)


@pytest.fixture
def shop(db):
    from django.utils import timezone

    now = timezone.now()
    return Shop.objects.create(
        domain="scope-store.myshopify.com",
        shopify_gid="gid://shopify/Shop/777",
        access_token_encrypted=encrypt_token("shpat_scope_token"),
        access_token_expires_at=now + timedelta(hours=1),
        refresh_token_expires_at=now + timedelta(days=60),
        status=ShopStatus.ACTIVE,
        scopes="write_products,read_inventory",
    )


from datetime import timedelta  # noqa: E402


@pytest.mark.django_db
class TestGetGrantedScopes:
    @patch("apps.core.scopes._get_client")
    def test_returns_handles_as_set(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.execute.return_value = {
            "currentAppInstallation": {
                "id": "gid://shopify/AppInstallation/1",
                "accessScopes": {
                    "nodes": [
                        {"handle": "write_products"},
                        {"handle": "write_online_store_navigation"},
                        {"handle": "write_publications"},
                    ]
                },
            }
        }
        mock_get_client.return_value = mock_client

        granted = get_granted_scopes("scope-store.myshopify.com", "token")

        assert granted == {
            "write_products",
            "write_online_store_navigation",
            "write_publications",
        }
        mock_client.close.assert_called_once()


class TestMissingScopes:
    def test_all_missing(self):
        assert missing_scopes(set()) == list(REQUIRED_START_SCOPES)

    def test_none_missing(self):
        assert missing_scopes(set(REQUIRED_START_SCOPES)) == []

    def test_partial(self):
        granted = {"write_online_store_navigation"}
        assert missing_scopes(granted) == ["read_publications", "write_publications"]


class TestBuildRegrantUrl:
    def test_contains_new_scopes_and_client_id(self, settings):
        settings.SHOPIFY_API_KEY = "test_key_123"
        settings.APP_URL = "https://shop.mosaiq.marketing"

        url = build_regrant_url("scope-store.myshopify.com")

        assert url.startswith("https://scope-store.myshopify.com/admin/oauth/authorize?")
        assert "client_id=test_key_123" in url
        assert "write_online_store_navigation" in url
        assert "write_publications" in url
        assert "redirect_uri=https%3A%2F%2Fshop.mosaiq.marketing%2Fauth%2Fcallback" in url

    def test_base_scopes_included(self, settings):
        settings.SHOPIFY_API_KEY = "k"
        settings.APP_URL = "https://shop.mosaiq.marketing"

        url = build_regrant_url("scope-store.myshopify.com")

        # Base install scopes must be re-requested too, or the re-grant
        # would REMOVE them.
        assert "write_products" in url
        assert "read_inventory" in url


@pytest.mark.django_db
class TestCheckStartScopes:
    @patch("apps.core.scopes.get_granted_scopes")
    def test_ok_when_all_granted(self, mock_check, shop):
        mock_check.return_value = set(REQUIRED_START_SCOPES)

        result = check_start_scopes(shop)

        assert result["ok"] is True
        assert result["missing"] == []
        assert result["error"] is None
        assert "regrant_url" in result

    @patch("apps.core.scopes.get_granted_scopes")
    def test_blocks_when_scopes_missing(self, mock_check, shop):
        mock_check.return_value = {"write_products"}

        result = check_start_scopes(shop)

        assert result["ok"] is False
        assert result["missing"] == list(REQUIRED_START_SCOPES)
        assert result["error"] == "SCOPE_MISSING"

    @patch("apps.core.scopes.get_granted_scopes")
    def test_blocks_on_check_failure(self, mock_check, shop):
        """GraphQL failure → safe default is block, never allow."""
        mock_check.side_effect = RuntimeError("API down")

        result = check_start_scopes(shop)

        assert result["ok"] is False
        assert result["error"] == "SCOPE_MISSING"
        assert decrypt_token(shop.access_token_encrypted) == "shpat_scope_token"
