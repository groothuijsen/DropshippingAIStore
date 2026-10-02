"""Tests for T-004: webhooks, HMAC validation, deduplication, dispatch."""

import base64
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from apps.webhooks.hmac import validate_shopify_hmac
from apps.webhooks.models import WebhookReceipt
from apps.webhooks.tasks import process_webhook
from apps.webhooks.views import shopify_webhook

# ── HMAC validation tests ─────────────────────────────────────────────────


class TestHmacValidation:
    def test_valid_hmac(self):
        secret = b"test-secret-32-chars-long-for-hmac!!!"
        body = b'{"shop_domain":"test.myshopify.com"}'
        digest = hmac.new(secret, body, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("utf-8")

        with patch("apps.webhooks.hmac.settings") as mock_settings:
            mock_settings.SHOPIFY_API_SECRET = "test-secret-32-chars-long-for-hmac!!!"
            assert validate_shopify_hmac(body, expected) is True

    def test_invalid_hmac(self):
        body = b'{"shop_domain":"test.myshopify.com"}'

        with patch("apps.webhooks.hmac.settings") as mock_settings:
            mock_settings.SHOPIFY_API_SECRET = "test-secret-32-chars-long-for-hmac!!!"
            assert validate_shopify_hmac(body, "invalid-hmac") is False

    def test_empty_hmac(self):
        with patch("apps.webhooks.hmac.settings") as mock_settings:
            mock_settings.SHOPIFY_API_SECRET = "test-secret"
            assert validate_shopify_hmac(b"body", "") is False

    def test_empty_secret(self):
        with patch("apps.webhooks.hmac.settings") as mock_settings:
            mock_settings.SHOPIFY_API_SECRET = ""
            assert validate_shopify_hmac(b"body", "some-hmac") is False


# ── WebhookReceipt model tests ────────────────────────────────────────────


@pytest.mark.django_db
class TestWebhookReceipt:
    def test_str_processed(self):
        receipt = WebhookReceipt.objects.create(
            webhook_id="123",
            topic="shop/update",
            shop_domain="test.myshopify.com",
            processed=True,
        )
        assert "processed" in str(receipt)
        assert "shop/update" in str(receipt)

    def test_str_pending(self):
        receipt = WebhookReceipt.objects.create(
            webhook_id="456",
            topic="app/uninstalled",
            shop_domain="test.myshopify.com",
        )
        assert "pending" in str(receipt)

    def test_unique_webhook_id(self):
        WebhookReceipt.objects.create(
            webhook_id="789",
            topic="shop/update",
            shop_domain="test.myshopify.com",
        )
        with pytest.raises(Exception, match="UNIQUE constraint"):
            WebhookReceipt.objects.create(
                webhook_id="789",
                topic="shop/update",
                shop_domain="test.myshopify.com",
            )


# ── Webhook endpoint tests ────────────────────────────────────────────────


@pytest.mark.django_db
class TestShopifyWebhookEndpoint:
    def _make_hmac(self, body: bytes, secret: str = "test-secret-32-chars-long-for-hmac!!!") -> str:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _post_webhook(self, body: dict, topic: str = "shop/update", webhook_id: str = "wh_123"):
        factory = RequestFactory()
        raw = json.dumps(body).encode()
        hmac_value = self._make_hmac(raw)
        return factory.post(
            "/webhooks/shopify/",
            data=raw,
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256=hmac_value,
            HTTP_X_SHOPIFY_TOPIC=topic,
            HTTP_X_SHOPIFY_WEBHOOK_ID=webhook_id,
        )

    @patch("apps.webhooks.tasks.process_webhook.delay")
    def test_valid_webhook_returns_200(self, mock_task):
        request = self._post_webhook({"shop_domain": "test.myshopify.com"})
        response = shopify_webhook(request)
        assert response.status_code == 200
        assert mock_task.called

    @patch("apps.webhooks.tasks.process_webhook.delay")
    def test_deduplication(self, mock_task):
        request = self._post_webhook(
            {"shop_domain": "test.myshopify.com"},
            webhook_id="wh_dup_1",
        )
        response = shopify_webhook(request)
        assert response.status_code == 200

        # Second request with same webhook_id
        request2 = self._post_webhook(
            {"shop_domain": "test.myshopify.com"},
            webhook_id="wh_dup_1",
        )
        response2 = shopify_webhook(request2)
        assert response2.status_code == 200
        # Task should only be called once
        assert mock_task.call_count == 1

    def test_invalid_hmac_returns_401(self):
        factory = RequestFactory()
        request = factory.post(
            "/webhooks/shopify/",
            data=b'{"test": true}',
            content_type="application/json",
            HTTP_X_SHOPIFY_HMAC_SHA256="invalid-hmac",
            HTTP_X_SHOPIFY_TOPIC="shop/update",
            HTTP_X_SHOPIFY_WEBHOOK_ID="wh_bad",
        )
        response = shopify_webhook(request)
        assert response.status_code == 401


# ── Webhook task tests ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestWebhookTasks:
    def test_process_webhook_marks_processed(self):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_task_1",
            topic="shop/update",
            shop_domain="test.myshopify.com",
        )
        process_webhook(receipt.id)
        receipt.refresh_from_db()
        assert receipt.processed is True

    def test_process_webhook_skips_unknown_topic(self):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_unknown",
            topic="unknown/topic",
            shop_domain="test.myshopify.com",
        )
        process_webhook(receipt.id)
        receipt.refresh_from_db()
        assert receipt.processed is True

    def test_process_webhook_skips_already_processed(self):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_done",
            topic="shop/update",
            shop_domain="test.myshopify.com",
            processed=True,
        )
        process_webhook(receipt.id)
        # Should not error

    def test_handle_app_uninstalled(self):
        from django.utils import timezone

        from apps.core.models import Shop, ShopStatus
        from apps.webhooks.tasks import handle_app_uninstalled

        shop = Shop.objects.create(
            domain="uninstall.myshopify.com",
            shopify_gid="gid://shopify/Shop/999",
            access_token_encrypted=b"encrypted",
            refresh_token_encrypted=b"encrypted",
            installed_at=timezone.now() - timezone.timedelta(days=30),
        )
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh_uninstall",
            topic="app/uninstalled",
            shop_domain="uninstall.myshopify.com",
        )
        handle_app_uninstalled(receipt)

        shop.refresh_from_db()
        assert shop.status == ShopStatus.UNINSTALLED
        assert shop.uninstalled_at is not None
        assert shop.access_token_encrypted == b""
