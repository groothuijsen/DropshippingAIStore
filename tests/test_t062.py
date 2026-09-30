"""Tests for T-062: TrialLedger + cancellation + plan changes + reconcile."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.billing.cancellation import cancel_subscription
from apps.billing.emails import (
    CANCEL_CONFIRMATION_SUBJECT,
    TRIAL_REMINDER_SUBJECT,
    send_cancellation_confirmation,
    send_trial_reminder,
)
from apps.billing.models import Subscription, TrialLedger
from apps.billing.plan_changes import (
    change_plan,
    get_replacement_behavior,
    is_upgrade,
)
from apps.billing.tasks import (
    check_trial_expiring,
    get_trial_days_for_domain,
    record_trial_started,
)
from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus


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
def subscription(db, shop):
    return Subscription.objects.create(
        shop=shop,
        plan="starter",
        shopify_subscription_gid="gid://shopify/AppSubscription/1",
        status="active",
        trial_ends_at=timezone.now() + timedelta(hours=24),
        current_period_end=timezone.now() + timedelta(days=30),
    )


class TestTrialLedger:
    def test_get_trial_days_new_domain(self, db):
        assert get_trial_days_for_domain("new-domain.myshopify.com") == 7

    def test_get_trial_days_existing_domain(self, db):
        record_trial_started("existing-domain.myshopify.com")
        assert get_trial_days_for_domain("existing-domain.myshopify.com") == 0

    def test_record_trial_started_idempotent(self, db):
        record_trial_started("test-domain.myshopify.com")
        record_trial_started("test-domain.myshopify.com")
        assert (
            TrialLedger.objects.filter(
                domain_sha256__isnull=False,
            ).count()
            == 1
        )

    def test_trial_ledger_no_shop_fk(self, db):
        """TrialLedger has no FK to Shop — persists after shop/redact."""
        record_trial_ledger = TrialLedger.objects.create(
            domain_sha256="abc123",
            first_trial_at=timezone.now(),
        )
        assert record_trial_ledger.pk is not None


class TestEmails:
    def test_send_trial_reminder(self, db):
        result = send_trial_reminder("test.myshopify.com", "2026-10-02", "https://cancel-url")
        assert result["sent"] is True
        assert result["subject"] == TRIAL_REMINDER_SUBJECT
        assert "2026-10-02" in result["body"]
        assert "https://cancel-url" in result["body"]

    def test_send_cancellation_confirmation(self, db):
        result = send_cancellation_confirmation("test.myshopify.com")
        assert result["sent"] is True
        assert result["subject"] == CANCEL_CONFIRMATION_SUBJECT


class TestPlanChanges:
    def test_is_upgrade(self):
        assert is_upgrade("starter", "pro") is True
        assert is_upgrade("pro", "agency") is True
        assert is_upgrade("pro", "starter") is False
        assert is_upgrade("starter", "starter") is False

    def test_replacement_behavior_upgrade(self):
        assert get_replacement_behavior("starter", "pro") == "APPLY_IMMEDIATELY"

    def test_replacement_behavior_downgrade(self):
        assert get_replacement_behavior("pro", "starter") == "APPLY_ON_NEXT_BILLING_CYCLE"

    @patch("apps.billing.plan_changes.ShopifyGraphQLClient")
    def test_change_plan_upgrade(self, mock_client_cls, shop, subscription):
        mock_client = mock_client_cls.return_value
        mock_client.execute.return_value = {
            "appSubscriptionCreate": {
                "confirmationUrl": "https://billing-confirmation",
                "appSubscription": {"id": "gid://shopify/AppSubscription/2", "status": "pending"},
                "userErrors": [],
            },
        }
        mock_client.close = MagicMock()

        ok, msg, result = change_plan(shop, subscription, "pro")
        assert ok is True
        assert result["replacement_behavior"] == "APPLY_IMMEDIATELY"
        assert result["is_upgrade"] is True

        # Verify call used correct replacement behavior
        call_kwargs = mock_client.execute.call_args
        variables = call_kwargs[1]["variables"]
        assert variables["replacementBehavior"] == "APPLY_IMMEDIATELY"

    @patch("apps.billing.plan_changes.ShopifyGraphQLClient")
    def test_change_plan_downgrade(self, mock_client_cls, shop, subscription):
        mock_client = mock_client_cls.return_value
        mock_client.execute.return_value = {
            "appSubscriptionCreate": {
                "confirmationUrl": "https://billing-confirmation",
                "appSubscription": {"id": "gid://shopify/AppSubscription/2", "status": "pending"},
                "userErrors": [],
            },
        }
        mock_client.close = MagicMock()

        subscription.plan = "pro"
        subscription.save(update_fields=["plan"])

        ok, msg, result = change_plan(shop, subscription, "starter")
        assert ok is True
        assert result["replacement_behavior"] == "APPLY_ON_NEXT_BILLING_CYCLE"
        assert result["is_upgrade"] is False

    @patch("apps.billing.plan_changes.ShopifyGraphQLClient")
    def test_change_plan_user_errors(self, mock_client_cls, shop, subscription):
        mock_client = mock_client_cls.return_value
        mock_client.execute.return_value = {
            "appSubscriptionCreate": {
                "confirmationUrl": "",
                "appSubscription": None,
                "userErrors": [{"message": "Invalid plan"}],
            },
        }
        mock_client.close = MagicMock()

        ok, msg, result = change_plan(shop, subscription, "pro")
        assert ok is False
        assert "Invalid plan" in msg


class TestCancellation:
    @patch("apps.billing.cancellation.ShopifyGraphQLClient")
    @patch("apps.billing.cancellation.send_cancellation_confirmation")
    def test_cancel_subscription_success(self, mock_email, mock_client_cls, shop, subscription):
        mock_client = mock_client_cls.return_value
        mock_client.execute.return_value = {
            "appSubscriptionCancel": {
                "appSubscription": {"id": "gid://shopify/AppSubscription/1", "status": "CANCELLED"},
                "userErrors": [],
            },
        }
        mock_client.close = MagicMock()
        mock_email.return_value = {"sent": True}

        ok, msg, result = cancel_subscription(shop, subscription)
        assert ok is True
        subscription.refresh_from_db()
        assert subscription.status == "cancelled"

    @patch("apps.billing.cancellation.ShopifyGraphQLClient")
    @patch("apps.billing.cancellation.send_cancellation_confirmation")
    def test_cancel_subscription_user_errors(self, mock_email, mock_client_cls, shop, subscription):
        mock_client = mock_client_cls.return_value
        mock_client.execute.return_value = {
            "appSubscriptionCancel": {
                "appSubscription": None,
                "userErrors": [{"message": "Not found"}],
            },
        }
        mock_client.close = MagicMock()
        mock_email.return_value = {"sent": True}

        ok, msg, result = cancel_subscription(shop, subscription)
        assert ok is False
        assert "Not found" in msg
        subscription.refresh_from_db()
        assert subscription.status == "active"

    @patch("apps.billing.cancellation.ShopifyGraphQLClient")
    def test_cancel_no_gid(self, mock_client_cls, shop, subscription):
        subscription.shopify_subscription_gid = ""
        subscription.save(update_fields=["shopify_subscription_gid"])

        ok, msg, result = cancel_subscription(shop, subscription)
        assert ok is False
        assert "No Shopify" in msg


class TestTrialExpiring:
    def test_check_trial_expiring_sends_email(self, db, shop, subscription):
        """Trials ending within 48h → reminder sent."""
        # subscription already has trial_ends_at 24h from now (from fixture)
        with patch("apps.billing.emails.send_trial_reminder") as mock_send:
            mock_send.return_value = {"sent": True}
            result = check_trial_expiring()
            assert result["expiring_soon"] == 1
            mock_send.assert_called_once()

    def test_check_trial_expiring_no_soon(self, db, shop):
        Subscription.objects.create(
            shop=shop,
            plan="starter",
            status="active",
            trial_ends_at=timezone.now() + timedelta(days=30),
        )
        with patch("apps.billing.emails.send_trial_reminder") as mock_send:
            result = check_trial_expiring()
            assert result["expiring_soon"] == 0
            mock_send.assert_not_called()
