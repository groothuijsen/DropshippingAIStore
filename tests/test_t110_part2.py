"""Tests for T-110 (part 2): webhook products/create, receiver fixes, OAuth callback.

Based on live-verified behaviour (2026-10-01):
- Webhook receipts must record shop_domain from X-Shopify-Shop-Domain
  (the receiver had a bug assigning the HMAC header to shop_domain).
- The parsed body must be stored on the receipt (body_json) so handlers
  can read it.
- products/create handler snapshots initial variant prices into
  PriceHistory (same semantics as products/update).
- /auth/callback (registered redirect URL, previously 404) validates the
  Shopify OAuth hmac and redirects back to the admin app page.
"""

import base64
import hashlib
import hmac as hmac_lib
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from apps.core.models import Shop
from apps.core.views import oauth_callback
from apps.webhooks.models import WebhookReceipt
from apps.webhooks.tasks import handle_product_create, process_webhook
from apps.webhooks.views import shopify_webhook

SECRET = "test-secret-32-chars-long-for-hmac!!!"


def _make_hmac(body: bytes, secret: str = SECRET) -> str:
    digest = hashlib.sha256(secret.encode() + body).digest()
    return base64.b64encode(digest).decode("utf-8")


PRODUCT_PAYLOAD = {
    "id": 123456789,
    "title": "Test Product",
    "admin_graphql_api_id": "gid://shopify/Product/123456789",
    "variants": [
        {
            "id": 987654321,
            "price": "19.95",
            "admin_graphql_api_id": "gid://shopify/ProductVariant/987654321",
        }
    ],
}


@pytest.mark.django_db
class TestWebhookReceiverFixes:
    def _post(self, body: dict, topic: str, webhook_id: str, shop_domain: str):
        factory = RequestFactory()
        raw = json.dumps(body).encode()
        return factory.post(
            "/webhooks/shopify/",
            data=raw,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=_make_hmac(raw),
            HTTP_X_SHOPIFY_TOPIC=topic,
            HTTP_X_SHOPIFY_WEBHOOK_ID=webhook_id,
            HTTP_X_SHOPIFY_SHOP_DOMAIN=shop_domain,
        )

    @patch("apps.webhooks.tasks.process_webhook.delay")
    def test_receipt_records_shop_domain_from_header(self, mock_task):
        """shop_domain must come from X-Shopify-Shop-Domain, not the HMAC header."""
        request = self._post(
            PRODUCT_PAYLOAD, "products/create", "wh_t110_1", "shop1.myshopify.com"
        )
        response = shopify_webhook(request)
        assert response.status_code == 200

        receipt = WebhookReceipt.objects.get(webhook_id="wh_t110_1")
        assert receipt.shop_domain == "shop1.myshopify.com"

    @patch("apps.webhooks.tasks.process_webhook.delay")
    def test_receipt_stores_body_json(self, mock_task):
        """The parsed payload must be stored on the receipt for handlers."""
        request = self._post(
            PRODUCT_PAYLOAD, "products/create", "wh_t110_2", "shop1.myshopify.com"
        )
        shopify_webhook(request)

        receipt = WebhookReceipt.objects.get(webhook_id="wh_t110_2")
        assert receipt.body_json is not None
        assert receipt.body_json["title"] == "Test Product"


@pytest.mark.django_db
class TestHandleProductCreate:
    @pytest.fixture
    def shop(self):
        return Shop.objects.create(
            domain="create.myshopify.com",
            shopify_gid="gid://shopify/Shop/888",
            access_token_encrypted=b"e",
            refresh_token_encrypted=b"e",
        )

    def test_snapshot_initial_prices(self, shop):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_pc_1",
            topic="products/create",
            shop_domain=shop.domain,
            body_json=PRODUCT_PAYLOAD,
        )
        handle_product_create(receipt)

        from apps.compliance.models import PriceHistory

        row = PriceHistory.objects.get(shop=shop)
        assert row.price == Decimal("19.95")
        assert row.variant_gid == "gid://shopify/ProductVariant/987654321"
        assert row.source == "webhook"

    def test_duplicate_create_does_not_duplicate_rows(self, shop):
        """Webhook retries must be idempotent (same price → no new row)."""
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_pc_2",
            topic="products/create",
            shop_domain=shop.domain,
            body_json=PRODUCT_PAYLOAD,
        )
        handle_product_create(receipt)
        handle_product_create(receipt)  # simulate a retry

        from apps.compliance.models import PriceHistory

        assert PriceHistory.objects.filter(shop=shop).count() == 1

    def test_unknown_shop_is_a_noop(self):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_pc_3",
            topic="products/create",
            shop_domain="unknown.myshopify.com",
            body_json=PRODUCT_PAYLOAD,
        )
        handle_product_create(receipt)  # must not raise

    def test_dispatches_through_process_webhook(self, shop):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_pc_4",
            topic="products/create",
            shop_domain=shop.domain,
            body_json=PRODUCT_PAYLOAD,
        )
        process_webhook(receipt.id)
        receipt.refresh_from_db()
        assert receipt.processed is True


# ── OAuth callback (T-110: /auth/callback was registered but 404'd) ────────


def _oauth_callback_query(shop: str, secret: str = SECRET) -> tuple[str, str]:
    """Build a valid Shopify OAuth callback query string + hmac."""
    params = {
        "code": "test-auth-code",
        "host": base64.b64encode(f"{shop}/admin".encode()).decode(),
        "shop": shop,
        "timestamp": "1727790000",
    }
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hmac_lib.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return qs, digest


@pytest.mark.django_db
class TestOAuthCallbackView:
    def _get(self, qs: str, hmac_value: str):

        factory = RequestFactory()
        return factory.get(f"/auth/callback?{qs}&hmac={hmac_value}")

    def test_valid_hmac_redirects_to_admin_app(self, settings):
        settings.SHOPIFY_API_SECRET = SECRET
        settings.SHOPIFY_API_KEY = "test_key_123"
        qs, hmac_value = _oauth_callback_query("oauth-test.myshopify.com")
        response = oauth_callback(self._get(qs, hmac_value))
        assert response.status_code == 302
        assert response["Location"] == (
            "https://oauth-test.myshopify.com/admin/apps/test_key_123"
        )

    def test_invalid_hmac_returns_404(self, settings):
        settings.SHOPIFY_API_SECRET = SECRET
        qs, _ = _oauth_callback_query("oauth-test.myshopify.com")
        response = oauth_callback(self._get(qs, hmac_value="bad-hmac"))
        assert response.status_code == 404

    def test_missing_hmac_returns_404(self, settings):
        from apps.core.views import oauth_callback

        settings.SHOPIFY_API_SECRET = SECRET
        factory = RequestFactory()
        response = oauth_callback(factory.get("/auth/callback?shop=x.myshopify.com"))
        assert response.status_code == 404

    def test_wrong_secret_rejected(self, settings):
        settings.SHOPIFY_API_SECRET = "another-secret"
        settings.SHOPIFY_API_KEY = "test_key_123"
        qs, hmac_value = _oauth_callback_query("oauth-test.myshopify.com", SECRET)
        response = oauth_callback(self._get(qs, hmac_value))
        assert response.status_code == 404
