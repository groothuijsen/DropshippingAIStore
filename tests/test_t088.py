"""Tests for T-088: withdrawal form + WithdrawalRequest + GDPR webhooks."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.compliance.models import WithdrawalRequest, WithdrawalRequestStatus
from apps.compliance.withdrawal import (
    check_rate_limit,
    create_withdrawal_request,
    generate_reference,
    get_withdrawal_labels_for,
    list_withdrawal_requests,
    mark_as_handled,
    validate_step1_form,
)
from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.core.proxy import validate_proxy_signature
from apps.webhooks.models import WebhookReceipt
from apps.webhooks.tasks import handle_customer_data_request, handle_customer_redact


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


class TestProxySignature:
    def test_valid_signature(self):
        import hashlib
        import hmac
        from urllib.parse import urlencode

        params = {"shop": "test.myshopify.com", "path": "withdraw", "locale": "nl"}
        message = urlencode(sorted(params.items()))
        secret = "test_secret"
        signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

        params["signature"] = signature
        assert validate_proxy_signature(params, secret) is True

    def test_invalid_signature(self):
        params = {"shop": "test.myshopify.com", "signature": "wrong"}
        assert validate_proxy_signature(params, "secret") is False

    def test_missing_signature(self):
        params = {"shop": "test.myshopify.com"}
        assert validate_proxy_signature(params, "secret") is False


class TestValidateStep1:
    def test_valid(self):
        ok, msg = validate_step1_form("Jan", "ORD-123", "jan@example.com", "")
        assert ok is True

    def test_honeypot_filled(self):
        ok, msg = validate_step1_form("Jan", "ORD-123", "jan@example.com", "filled")
        assert ok is False
        assert msg == "honeypot_filled"

    def test_missing_name(self):
        ok, msg = validate_step1_form("", "ORD-123", "jan@example.com", "")
        assert ok is False

    def test_missing_order(self):
        ok, msg = validate_step1_form("Jan", "", "jan@example.com", "")
        assert ok is False

    def test_invalid_email(self):
        ok, msg = validate_step1_form("Jan", "ORD-123", "not-an-email", "")
        assert ok is False


class TestGenerateReference:
    def test_format(self, db):
        ref = generate_reference()
        assert ref.startswith("MQW-")
        assert len(ref) == 10

    def test_unique(self, db):
        refs = {generate_reference() for _ in range(100)}
        assert len(refs) == 100


class TestCreateWithdrawalRequest:
    @patch("apps.compliance.tasks.send_withdrawal_confirmation.delay")
    @patch("apps.compliance.tasks.notify_merchant.delay")
    def test_create(self, mock_notify, mock_confirm, shop):
        request = create_withdrawal_request(
            shop,
            "Jan Jansen",
            "ORD-123",
            "jan@example.com",
            "nl",
        )
        assert request.reference.startswith("MQW-")
        assert request.customer_name == "Jan Jansen"
        assert request.status == WithdrawalRequestStatus.SUBMITTED
        assert request.submitted_at is not None
        mock_confirm.assert_called_once()
        mock_notify.assert_called_once()

    @patch("apps.compliance.tasks.send_withdrawal_confirmation.delay")
    @patch("apps.compliance.tasks.notify_merchant.delay")
    def test_create_strips_whitespace(self, mock_notify, mock_confirm, shop):
        request = create_withdrawal_request(
            shop,
            "  Jan Jansen  ",
            "  ORD-123  ",
            "jan@example.com",
            "nl",
        )
        assert request.customer_name == "Jan Jansen"
        assert request.order_identifier == "ORD-123"


class TestRateLimit:
    def test_within_limit(self, shop):
        assert check_rate_limit(shop, "1.2.3.4") is True

    @patch("apps.compliance.tasks.send_withdrawal_confirmation.delay")
    @patch("apps.compliance.tasks.notify_merchant.delay")
    def test_over_limit(self, mock_notify, mock_confirm, shop):
        for i in range(50):
            WithdrawalRequest.objects.create(
                shop=shop,
                reference=f"MQW-TEST{i:04d}",
                customer_name="Test",
                order_identifier="ORD",
                email="t@e.com",
                locale="nl",
                submitted_at=timezone.now(),
            )
        assert check_rate_limit(shop, "1.2.3.4") is False


class TestLabels:
    def test_labels_for_locale(self):
        labels = get_withdrawal_labels_for("nl")
        assert labels["link"] == "Hier de overeenkomst ontbinden"
        assert labels["confirm"] == "Ontbinding bevestigen"

    def test_labels_fallback(self):
        labels = get_withdrawal_labels_for("fr")
        assert labels["link"] == "Withdraw from contract here"


class TestMerchantOverview:
    @patch("apps.compliance.tasks.send_withdrawal_confirmation.delay")
    @patch("apps.compliance.tasks.notify_merchant.delay")
    def test_list_requests(self, mock_notify, mock_confirm, shop):
        create_withdrawal_request(shop, "Jan", "ORD-1", "j@e.com", "nl")
        create_withdrawal_request(shop, "Piet", "ORD-2", "p@e.com", "de")
        requests = list_withdrawal_requests(shop)
        assert len(requests) == 2

    @patch("apps.compliance.tasks.send_withdrawal_confirmation.delay")
    @patch("apps.compliance.tasks.notify_merchant.delay")
    def test_mark_handled(self, mock_notify, mock_confirm, shop):
        request = create_withdrawal_request(shop, "Jan", "ORD-1", "j@e.com", "nl")
        ok, msg = mark_as_handled(shop, request.reference)
        assert ok is True
        request.refresh_from_db()
        assert request.status == WithdrawalRequestStatus.HANDLED

    def test_mark_handled_not_found(self, shop):
        ok, msg = mark_as_handled(shop, "MQW-XXXXXX")
        assert ok is False


class TestGDPRWebhooks:
    @patch("apps.compliance.tasks.send_withdrawal_confirmation.delay")
    @patch("apps.compliance.tasks.notify_merchant.delay")
    def test_customer_redact(self, mock_notify, mock_confirm, shop):
        """customers/redact deletes WithdrawalRequest rows (F11 criterion 20)."""
        create_withdrawal_request(shop, "Jan", "ORD-1", "jan@example.com", "nl")
        create_withdrawal_request(shop, "Piet", "ORD-2", "piet@example.com", "nl")

        receipt = WebhookReceipt.objects.create(
            webhook_id="wh-cust-redact-1",
            topic="customers/redact",
            shop_domain=shop.domain,
            body_json={"email": "jan@example.com"},
        )
        handle_customer_redact(receipt)

        assert not WithdrawalRequest.objects.filter(email="jan@example.com").exists()
        assert WithdrawalRequest.objects.filter(email="piet@example.com").exists()

    @patch("apps.compliance.tasks.send_withdrawal_confirmation.delay")
    @patch("apps.compliance.tasks.notify_merchant.delay")
    def test_customer_data_request(self, mock_notify, mock_confirm, shop):
        """customers/data_request exports WithdrawalRequest rows (F11 criterion 20)."""
        create_withdrawal_request(shop, "Jan", "ORD-1", "jan@example.com", "nl")

        receipt = WebhookReceipt.objects.create(
            webhook_id="wh-cust-dr-1",
            topic="customers/data_request",
            shop_domain=shop.domain,
            body_json={"email": "jan@example.com"},
        )
        # Should not raise; exports to merchant
        handle_customer_data_request(receipt)
        # Row still exists (export, not delete)
        assert WithdrawalRequest.objects.filter(email="jan@example.com").exists()
