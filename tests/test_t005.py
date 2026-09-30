"""Tests for T-005: GraphQL client, throttling, errors, .graphql loader."""

from unittest.mock import MagicMock, patch

import pytest

from apps.core.shopify_client import (
    ShopifyAuthError,
    ShopifyGraphQLClient,
    ShopifyGraphQLError,
    ShopifyThrottledError,
    ShopifyUserError,
    load_query,
)

# ── .graphql loader tests ─────────────────────────────────────────────────


class TestLoadQuery:
    def test_load_shop_info(self):
        query = load_query("shop_info")
        assert "shop" in query
        assert "currencyCode" in query
        assert "shopLocales" in query

    def test_load_current_installation(self):
        query = load_query("current_installation")
        assert "currentAppInstallation" in query
        assert "activeSubscriptions" in query

    def test_load_product_get(self):
        query = load_query("product_get")
        assert "product" in query
        assert "variants" in query
        assert "metafields" in query

    def test_load_products_list(self):
        query = load_query("products_list")
        assert "products" in query
        assert "pageInfo" in query

    def test_load_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            load_query("nonexistent_query")


# ── Client tests ──────────────────────────────────────────────────────────


class TestShopifyGraphQLClient:
    def _make_client(self) -> ShopifyGraphQLClient:
        return ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test_token",
            api_version="2026-07",
        )

    def test_endpoint_construction(self):
        client = self._make_client()
        assert "test-store.myshopify.com" in client.endpoint
        assert "2026-07" in client.endpoint
        assert "graphql.json" in client.endpoint

    def test_context_manager(self):
        client = self._make_client()
        with client:
            assert client._client is not None


# ── Success response tests ────────────────────────────────────────────────


class TestSuccessResponses:
    def test_normal_response(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "shop": {
                    "id": "gid://shopify/Shop/123",
                    "name": "Test Store",
                    "email": "test@example.com",
                    "currencyCode": "EUR",
                    "ianaTimezone": "Europe/Amsterdam",
                }
            }
        }

        with patch.object(client._client, "post", return_value=mock_resp):
            result = client.execute("query { shop { id } }")
            assert result["shop"]["id"] == "gid://shopify/Shop/123"


# ── Error tests ───────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_top_level_errors(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": [{"message": "Cannot query field 'foo'"}]}

        with patch.object(client._client, "post", return_value=mock_resp):
            with pytest.raises(ShopifyGraphQLError) as exc_info:
                client.execute("query { foo }")
            assert "Cannot query field" in str(exc_info.value)

    def test_user_errors(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "productSet": {
                    "userErrors": [
                        {
                            "field": "title",
                            "message": "Title is required",
                            "code": "BLANK",
                        }
                    ]
                }
            }
        }

        with patch.object(client._client, "post", return_value=mock_resp):
            with pytest.raises(ShopifyUserError) as exc_info:
                client.execute("mutation { productSet { userErrors } }")
            assert exc_info.value.field == "title"
            assert exc_info.value.code == "BLANK"

    def test_http_401_raises_auth_error(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch.object(client._client, "post", return_value=mock_resp), pytest.raises(ShopifyAuthError):
            client.execute("query { shop { id } }")

    def test_http_403_raises_auth_error(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch.object(client._client, "post", return_value=mock_resp), pytest.raises(ShopifyAuthError):
            client.execute("query { shop { id } }")


# ── Throttling tests ──────────────────────────────────────────────────────


class TestThrottling:
    def test_throttled_retries_and_succeeds(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        throttle_resp = MagicMock()
        throttle_resp.status_code = 200
        throttle_resp.json.return_value = {"errors": [{"extensions": {"code": "THROTTLED"}, "message": "Throttled"}]}
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"data": {"shop": {"id": "1"}}}

        with (
            patch.object(client._client, "post", side_effect=[throttle_resp, ok_resp]),
            patch("apps.core.shopify_client.time.sleep") as mock_sleep,
        ):
            result = client.execute("query { shop { id } }")
            assert result["shop"]["id"] == "1"
            assert mock_sleep.called

    def test_throttled_exhausts_retries(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        throttle_resp = MagicMock()
        throttle_resp.status_code = 200
        throttle_resp.json.return_value = {"errors": [{"extensions": {"code": "THROTTLED"}, "message": "Throttled"}]}

        with (
            patch.object(client._client, "post", return_value=throttle_resp),
            patch("apps.core.shopify_client.time.sleep"),
            pytest.raises(ShopifyThrottledError),
        ):
            client.execute("query { shop { id } }")

    def test_proactive_throttle_wait(self):
        client = ShopifyGraphQLClient(
            shop_domain="test-store.myshopify.com",
            access_token="shpat_test",
            api_version="2026-07",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"shop": {"id": "1"}},
            "extensions": {
                "cost": {
                    "requestedQueryCost": 50,
                    "throttleStatus": {
                        "currentlyAvailable": 20,
                        "restoreRate": 2,
                    },
                }
            },
        }

        with (
            patch.object(client._client, "post", return_value=mock_resp),
            patch("apps.core.shopify_client.time.sleep") as mock_sleep,
        ):
            client.execute("query { shop { id } }")
            # Should have waited (50 - 20) / 2 = 15 seconds
            mock_sleep.assert_called_once_with(15.0)


# ── Exception str tests ──────────────────────────────────────────────────


class TestExceptionStrings:
    def test_shopify_graphql_error_str(self):
        exc = ShopifyGraphQLError([{"message": "Field not found"}])
        assert "Field not found" in str(exc)

    def test_shopify_user_error_str(self):
        exc = ShopifyUserError(field="title", message="Required", code="BLANK")
        assert "title" in str(exc)
        assert "Required" in str(exc)
        assert "BLANK" in str(exc)

    def test_shopify_throttled_str(self):
        exc = ShopifyThrottledError("Rate limit exceeded")
        assert "Rate limit exceeded" in str(exc)
