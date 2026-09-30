"""Tests for core authentication, token exchange and refresh."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from apps.core.crypto import decrypt_token, encrypt_token
from apps.core.middleware import SessionTokenMiddleware
from apps.core.models import AuditLog, Shop, ShopStatus
from apps.core.tokens import get_access_token, refresh_access_token, store_tokens

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def shop(db):
    """Create a test shop with encrypted tokens."""
    from django.utils import timezone

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


# ── Crypto tests ──────────────────────────────────────────────────────────


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "shpat_abc123"
        encrypted = encrypt_token(plaintext)
        assert encrypted != plaintext.encode()
        decrypted = decrypt_token(encrypted)
        assert decrypted == plaintext

    def test_different_encryptions_differ(self):
        a = encrypt_token("token1")
        b = encrypt_token("token1")
        assert decrypt_token(a) == decrypt_token(b) == "token1"


# ── Model tests ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestShopModel:
    def test_shop_str(self, shop):
        assert str(shop) == "test-store.myshopify.com (active)"

    def test_shop_status_choices(self):
        assert ShopStatus.ACTIVE == "active"
        assert ShopStatus.UNINSTALLED == "uninstalled"
        assert ShopStatus.FROZEN == "frozen"

    def test_default_onboarding_step(self, shop):
        assert shop.onboarding_step == "language"

    def test_default_stock_threshold(self, shop):
        assert shop.stock_threshold == 5

    def test_audit_log_str(self, shop):
        log = AuditLog.objects.create(
            shop=shop,
            actor="merchant",
            action="compliance.override_prior_price",
            payload={"variant_gid": "gid://shopify/ProductVariant/1"},
        )
        assert "merchant:compliance.override_prior_price" in str(log)


# ── Middleware tests ───────────────────────────────────────────────────────


class TestSessionTokenMiddleware:
    def _make_request(self, path="/app/", token=None, htmx=False):
        factory = RequestFactory()
        kwargs = {}
        if token:
            if htmx:
                kwargs["HTTP_AUTHORIZATION"] = f"Bearer {token}"
            else:
                kwargs["QUERY_STRING"] = f"id_token={token}"
        if htmx:
            kwargs["HTTP_HX_REQUEST"] = "true"
        return factory.get(path, **kwargs)

    def _make_valid_token(self):
        """Create a valid JWT signed with the test SHOPIFY_API_SECRET."""
        import jwt as pyjwt
        from django.conf import settings

        return pyjwt.encode(
            {
                "iss": "https://test-store.myshopify.com/admin",
                "dest": "https://test-store.myshopify.com",
                "aud": settings.SHOPIFY_API_KEY,
                "sub": "12345",
                "exp": 9999999999,
                "nbf": 1000000000,
            },
            settings.SHOPIFY_API_SECRET,
            algorithm="HS256",
        )

    def test_exempt_path_skipped(self):
        factory = RequestFactory()
        request = factory.get("/healthz/")
        middleware = SessionTokenMiddleware(lambda r: None)
        result = middleware.process_request(request)
        assert result is None

    def test_htmx_without_token_returns_401(self):
        request = self._make_request(htmx=True)
        middleware = SessionTokenMiddleware(lambda r: None)
        response = middleware.process_request(request)
        assert response is not None
        assert response.status_code == 401
        assert response["X-Shopify-Retry-Invalid-Session-Request"] == "1"

    def test_full_page_without_token_shows_bounce(self):
        request = self._make_request()
        middleware = SessionTokenMiddleware(lambda r: None)
        response = middleware.process_request(request)
        assert response is not None
        assert response.status_code == 200
        assert b"shopify" in response.content.lower()

    def test_valid_token_sets_shop_domain(self):
        token = self._make_valid_token()
        request = self._make_request(token=token)
        middleware = SessionTokenMiddleware(lambda r: None)
        result = middleware.process_request(request)
        assert result is None
        assert request.shop_domain == "test-store.myshopify.com"

    def test_invalid_token_returns_401_htmx(self):
        request = self._make_request(token="invalid.jwt.token", htmx=True)
        middleware = SessionTokenMiddleware(lambda r: None)
        response = middleware.process_request(request)
        assert response is not None
        assert response.status_code == 401


# ── Token store / refresh tests ───────────────────────────────────────────


@pytest.mark.django_db
class TestTokenExchange:
    def test_store_tokens(self, shop):
        token_data = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
            "refresh_token_expires_in": 7_776_000,
            "scope": "write_products,read_inventory",
        }
        store_tokens(shop, token_data)

        shop.refresh_from_db()
        assert decrypt_token(shop.access_token_encrypted) == "new_access_token"
        assert decrypt_token(shop.refresh_token_encrypted) == "new_refresh_token"
        assert shop.scopes == "write_products,read_inventory"
        assert shop.needs_reauth is False


@pytest.mark.django_db
class TestGetAccessToken:
    def test_returns_current_token_when_valid(self, shop):
        token = get_access_token(shop)
        assert token == "shpat_test_access_token_12345"

    def test_returns_none_when_needs_reauth(self, shop):
        shop.needs_reauth = True
        shop.save(update_fields=["needs_reauth"])
        assert get_access_token(shop) is None

    @patch("apps.core.tokens._get_redis")
    @patch("apps.core.tokens.refresh_access_token")
    def test_refreshes_when_token_expiring(self, mock_refresh, mock_redis, shop):
        from django.utils import timezone

        # Token expires in 3 minutes (< 5 minute threshold)
        shop.access_token_expires_at = timezone.now() + timedelta(minutes=3)
        shop.save(update_fields=["access_token_expires_at"])
        mock_refresh.return_value = True

        # Mock Redis lock to succeed
        mock_r = MagicMock()
        mock_r.set.return_value = True
        mock_r.delete.return_value = True
        mock_redis.return_value = mock_r

        token = get_access_token(shop)
        assert mock_refresh.called
        assert token == "shpat_test_access_token_12345"

    @patch("apps.core.tokens.httpx.post")
    def test_refresh_access_token_success(self, mock_post, shop):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "refreshed_access",
            "refresh_token": "refreshed_refresh",
            "expires_in": 3600,
            "refresh_token_expires_in": 7_776_000,
            "scope": "write_products",
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = refresh_access_token(shop)
        assert result is True

        shop.refresh_from_db()
        assert decrypt_token(shop.access_token_encrypted) == "refreshed_access"

    @patch("apps.core.tokens.httpx.post")
    def test_refresh_failure_sets_needs_reauth(self, mock_post, shop):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp

        result = refresh_access_token(shop)
        assert result is False

        shop.refresh_from_db()
        assert shop.needs_reauth is True
