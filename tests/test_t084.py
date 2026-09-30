"""Tests for T-084: uninstall, shop/redact, export."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing.models import Subscription, TrialLedger
from apps.core.crypto import encrypt_token
from apps.core.export import export_shop_data, export_to_json
from apps.core.models import AuditLog, Shop, ShopStatus
from apps.generator.models import GenerationJob, JobKind, JobStatus, Page
from apps.offers.models import Offer
from apps.themes.models import BrandKit
from apps.webhooks.models import WebhookReceipt
from apps.webhooks.tasks import (
    handle_app_uninstalled,
    handle_shop_redact,
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
def receipt(shop):
    return WebhookReceipt.objects.create(
        webhook_id="wh-123",
        topic="app/uninstalled",
        shop_domain=shop.domain,
        body_json={"domain": shop.domain},
    )


@pytest.fixture
def running_job(db, shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type="pdp",
        content_locale="nl",
        input={},
        status=JobStatus.RUNNING,
        idempotency_key="test-job-running",
    )


@pytest.fixture
def queued_job(db, shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type="pdp",
        content_locale="nl",
        input={},
        status=JobStatus.QUEUED,
        idempotency_key="test-job-queued",
    )


class TestUninstall:
    def test_uninstall_sets_status(self, shop, receipt, running_job):
        handle_app_uninstalled(receipt)
        shop.refresh_from_db()
        assert shop.status == ShopStatus.UNINSTALLED
        assert shop.uninstalled_at is not None

    def test_uninstall_wipes_tokens(self, shop, receipt):
        handle_app_uninstalled(receipt)
        shop.refresh_from_db()
        assert shop.access_token_encrypted == b""
        assert shop.refresh_token_encrypted == b""

    def test_uninstall_cancels_running_jobs(self, shop, receipt, running_job, queued_job):
        handle_app_uninstalled(receipt)
        running_job.refresh_from_db()
        queued_job.refresh_from_db()
        assert running_job.status == JobStatus.CANCELLED
        assert queued_job.status == JobStatus.CANCELLED

    def test_uninstall_does_not_touch_succeeded_jobs(self, shop, receipt, db):
        job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.PAGE,
            page_type="pdp",
            content_locale="nl",
            input={},
            status=JobStatus.SUCCEEDED,
            idempotency_key="test-job-succeeded",
        )
        handle_app_uninstalled(receipt)
        job.refresh_from_db()
        assert job.status == JobStatus.SUCCEEDED

    def test_uninstall_creates_audit_log(self, shop, receipt, running_job):
        handle_app_uninstalled(receipt)
        log = AuditLog.objects.filter(shop=shop, action="uninstalled").first()
        assert log is not None
        assert log.actor == "system"
        assert log.payload["cancelled_jobs"] == 1

    def test_uninstall_no_shop(self, db):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh-999",
            topic="app/uninstalled",
            shop_domain="nonexistent.myshopify.com",
            body_json={},
        )
        # Should not raise
        handle_app_uninstalled(receipt)


class TestShopRedact:
    def _setup_content(self, shop):
        now = timezone.now()
        job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.PAGE,
            page_type="pdp",
            content_locale="nl",
            input={},
            status=JobStatus.SUCCEEDED,
            idempotency_key="redact-job",
        )
        Page.objects.create(
            shop=shop,
            job=job,
            page_type="pdp",
            title="Test",
            content_locale="nl",
            sections={"nl": {"sections": []}},
        )
        Offer.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="Test",
            kind="volume",
            config={},
            status="active",
        )
        Subscription.objects.create(
            shop=shop,
            plan="starter",
            status="active",
        )
        TrialLedger.objects.create(
            domain_sha256="abc123",
            first_trial_at=now,
        )

    def test_redact_deletes_shop_rows(self, shop):
        self._setup_content(shop)
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh-redact-1",
            topic="shop/redact",
            shop_domain=shop.domain,
            body_json={},
        )
        handle_shop_redact(receipt)
        assert not Shop.objects.filter(domain=shop.domain).exists()
        assert not GenerationJob.objects.filter(shop=shop).exists()
        assert not Page.objects.filter(shop=shop).exists()
        assert not Offer.objects.filter(shop=shop).exists()
        assert not Subscription.objects.filter(shop=shop).exists()

    def test_redact_keeps_trial_ledger(self, shop):
        """TrialLedger survives shop/redact (08 §4)."""
        self._setup_content(shop)
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh-redact-2",
            topic="shop/redact",
            shop_domain=shop.domain,
            body_json={},
        )
        handle_shop_redact(receipt)
        assert TrialLedger.objects.filter(domain_sha256="abc123").exists()

    def test_redact_ignores_reinstalled(self, shop):
        """If shop has been reinstalled, redact is ignored (F13 criterion 5)."""
        self._setup_content(shop)
        # Simulate reinstall: uninstalled_at set, then installed_at > uninstalled_at
        shop.uninstalled_at = timezone.now() - timedelta(hours=1)
        shop.save(update_fields=["uninstalled_at"])
        # installed_at is auto_now_add — simulate reinstall by setting it later
        Shop.objects.filter(pk=shop.pk).update(
            installed_at=timezone.now(),
            status=ShopStatus.ACTIVE,
        )
        shop.refresh_from_db()

        receipt = WebhookReceipt.objects.create(
            webhook_id="wh-redact-3",
            topic="shop/redact",
            shop_domain=shop.domain,
            body_json={},
        )
        handle_shop_redact(receipt)
        assert Shop.objects.filter(domain=shop.domain).exists()

    def test_redact_no_shop(self, db):
        receipt = WebhookReceipt.objects.create(
            webhook_id="wh-redact-4",
            topic="shop/redact",
            shop_domain="nonexistent.myshopify.com",
            body_json={},
        )
        # Should not raise
        handle_shop_redact(receipt)


class TestExport:
    def test_export_pages(self, shop):
        job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.PAGE,
            page_type="pdp",
            content_locale="nl",
            input={},
            status=JobStatus.SUCCEEDED,
            idempotency_key="export-job",
        )
        Page.objects.create(
            shop=shop,
            job=job,
            page_type="pdp",
            title="Export Test",
            content_locale="nl",
            sections={"nl": {"sections": [{"type": "hero", "headline": "Test"}]}},
            images={"hero": "gid://shopify/MediaImage/1"},
        )
        data = export_shop_data(shop)
        assert len(data["pages"]) == 1
        assert data["pages"][0]["title"] == "Export Test"

    def test_export_offers(self, shop):
        Offer.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            title="Export Offer",
            kind="volume",
            config={"tiers": []},
            status="active",
        )
        data = export_shop_data(shop)
        assert len(data["offers"]) == 1
        assert data["offers"][0]["title"] == "Export Offer"

    def test_export_brandkit(self, shop):
        BrandKit.objects.create(
            shop=shop,
            palette={"primary": "#000000"},
            font_heading="inter",
            font_body="inter",
            style_preset="modern",
        )
        data = export_shop_data(shop)
        assert data["brandkit"]["font_heading"] == "inter"

    def test_export_no_brandkit(self, shop):
        data = export_shop_data(shop)
        assert data["brandkit"] is None

    def test_export_no_tokens(self, shop):
        """Export never contains tokens (F13 criterion 7)."""
        data = export_to_json(shop)
        assert "shpat_" not in data
        assert "access_token" not in data

    def test_export_json_serializable(self, shop):
        json_str = export_to_json(shop)
        import json

        parsed = json.loads(json_str)
        assert "shop" in parsed
        assert "pages" in parsed
