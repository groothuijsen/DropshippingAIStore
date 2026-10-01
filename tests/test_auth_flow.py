"""Tests for the auth flow — token exchange + shop bootstrap on first load."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from django.test import Client
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus

pytestmark = pytest.mark.django_db


def _make_session_token(shop_domain: str, secret: str = "test-secret-32-chars-long-for-hmac!!!") -> str:
    """Create a valid Shopify session token (JWT)."""
    now = timezone.now()
    payload = {
        "iss": f"https://{shop_domain}/admin",
        "dest": f"https://{shop_domain}",
        "aud": "test-api-key-1234567890",
        "exp": (now + timedelta(minutes=5)).timestamp(),
        "nbf": (now - timedelta(seconds=10)).timestamp(),
        "sub": "12345",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def shop_domain():
    return "test-store.myshopify.com"


@pytest.fixture
def existing_shop(db, shop_domain):
    now = timezone.now()
    return Shop.objects.create(
        domain=shop_domain,
        shopify_gid="gid://shopify/Shop/123",
        name="Test Store",
        email="test@example.com",
        currency_code="EUR",
        access_token_encrypted=encrypt_token("shpat_existing_token"),
        access_token_expires_at=now + timedelta(hours=1),
        refresh_token_encrypted=encrypt_token("shpat_refresh_token"),
        refresh_token_expires_at=now + timedelta(days=90),
        status=ShopStatus.ACTIVE,
    )


class TestEnsureShop:
    """Tests for ensure_shop() — token exchange + shop bootstrap."""

    @patch("apps.core.tasks.run_on_install.delay")
    @patch("apps.core.auth_flow.ShopifyGraphQLClient")
    @patch("apps.core.auth_flow.exchange_token", new_callable=AsyncMock)
    def test_first_load_no_shop_performs_token_exchange(
        self,
        mock_exchange,
        mock_client_class,
        mock_run_install,
        db,
        shop_domain,
        settings,
    ):
        """First load with no Shop → token exchange → Shop created → on_install queued."""
        from apps.core.auth_flow import ensure_shop

        # Mock token exchange response
        mock_exchange.return_value = {
            "access_token": "shpat_new_token",
            "refresh_token": "shpat_new_refresh",
            "expires_in": 3600,
            "refresh_token_expires_in": 7_776_000,
            "scope": "write_products",
        }

        # Mock GraphQL client for shop_info
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.execute.return_value = {
            "shop": {
                "id": "gid://shopify/Shop/456",
                "name": "Test Store",
                "email": "test@example.com",
                "currencyCode": "EUR",
                "ianaTimezone": "Europe/Amsterdam",
                "billingAddress": {"countryCodeV2": "NL"},
            },
            "shopLocales": [{"locale": "en", "primary": True}],
        }

        # Create a mock request with shop_domain set by middleware
        request = MagicMock()
        request.shop_domain = shop_domain
        request.GET.get.return_value = "fake-session-token"
        request.META.get.return_value = ""

        shop = ensure_shop(request)

        assert shop is not None
        assert shop.domain == shop_domain
        assert shop.shopify_gid == "gid://shopify/Shop/456"
        mock_exchange.assert_called_once()
        mock_run_install.assert_called_once()

    @patch("apps.core.auth_flow.exchange_token", new_callable=AsyncMock)
    def test_existing_shop_with_valid_token_skips_exchange(
        self,
        mock_exchange,
        existing_shop,
        shop_domain,
    ):
        """Existing Shop with valid token → no token exchange."""
        from apps.core.auth_flow import ensure_shop

        request = MagicMock()
        request.shop_domain = shop_domain
        request.GET.get.return_value = "fake-session-token"
        request.META.get.return_value = ""

        shop = ensure_shop(request)

        assert shop is not None
        assert shop.id == existing_shop.id
        mock_exchange.assert_not_called()

    @patch("apps.core.tasks.run_on_install.delay")
    @patch("apps.core.auth_flow.ShopifyGraphQLClient")
    @patch("apps.core.auth_flow.exchange_token", new_callable=AsyncMock)
    def test_shop_needs_reauth_performs_token_exchange(
        self,
        mock_exchange,
        mock_client_class,
        mock_run_install,
        existing_shop,
        shop_domain,
    ):
        """Shop with needs_reauth=True → re-exchange token."""
        from apps.core.auth_flow import ensure_shop

        existing_shop.needs_reauth = True
        existing_shop.save(update_fields=["needs_reauth"])

        mock_exchange.return_value = {
            "access_token": "shpat_refreshed",
            "refresh_token": "shpat_refreshed_refresh",
            "expires_in": 3600,
            "refresh_token_expires_in": 7_776_000,
            "scope": "write_products",
        }

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.execute.return_value = {
            "shop": {
                "id": "gid://shopify/Shop/123",
                "name": "Test Store",
                "email": "test@example.com",
                "currencyCode": "EUR",
                "ianaTimezone": "Europe/Amsterdam",
                "billingAddress": {"countryCodeV2": "NL"},
            },
            "shopLocales": [{"locale": "en", "primary": True}],
        }

        request = MagicMock()
        request.shop_domain = shop_domain
        request.GET.get.return_value = "fake-session-token"
        request.META.get.return_value = ""

        shop = ensure_shop(request)

        assert shop is not None
        assert shop.needs_reauth is False
        mock_exchange.assert_called_once()

    def test_no_shop_domain_returns_none(self, db):
        """Request without shop_domain → returns None."""
        from apps.core.auth_flow import ensure_shop

        request = MagicMock()
        request.shop_domain = None

        shop = ensure_shop(request)

        assert shop is None


class TestDashboardView:
    """Tests for the dashboard view auth flow integration."""

    @patch("apps.core.tasks.run_on_install.delay")
    @patch("apps.core.auth_flow.ShopifyGraphQLClient")
    @patch("apps.core.auth_flow.exchange_token", new_callable=AsyncMock)
    def test_dashboard_first_load_bootstraps_shop(
        self,
        mock_exchange,
        mock_client_class,
        mock_run_install,
        db,
        shop_domain,
        settings,
    ):
        """Dashboard view on first load → shop bootstrapped."""
        mock_exchange.return_value = {
            "access_token": "shpat_new",
            "refresh_token": "shpat_new_refresh",
            "expires_in": 3600,
            "refresh_token_expires_in": 7_776_000,
            "scope": "write_products",
        }

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.execute.return_value = {
            "shop": {
                "id": "gid://shopify/Shop/789",
                "name": "My Store",
                "email": "owner@example.com",
                "currencyCode": "EUR",
                "ianaTimezone": "Europe/Amsterdam",
                "billingAddress": {"countryCodeV2": "NL"},
            },
            "shopLocales": [{"locale": "en", "primary": True}],
        }

        session_token = _make_session_token(shop_domain)
        client = Client()
        response = client.get(f"/app/?shop={shop_domain}&id_token={session_token}")

        assert response.status_code == 200
        shop = Shop.objects.filter(domain=shop_domain).first()
        assert shop is not None
        assert shop.shopify_gid == "gid://shopify/Shop/789"
        mock_run_install.assert_called_once()
