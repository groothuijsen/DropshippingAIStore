"""Tests for T-061: limits integration in the generator pipeline."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.billing.limits import (
    consume,
    get_usage_summary,
    release,
    reserve,
)
from apps.billing.models import Plan, Subscription, UsageCounter
from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.models import GenerationJob, JobStatus, JobStep, StepStatus
from apps.generator.tasks import execute_job


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
def starter_subscription(db, shop):
    return Subscription.objects.create(
        shop=shop,
        shopify_subscription_gid="gid://shopify/AppSubscription/123",
        plan=Plan.STARTER,
        status="active",
        current_period_end=timezone.now() + timedelta(days=15),
    )


def _make_job(shop, **kwargs):
    defaults = {
        "kind": "page",
        "content_locale": "nl",
        "input": {"product_gid": "gid://shopify/Product/123"},
        "status": JobStatus.QUEUED,
    }
    defaults.update(kwargs)
    return GenerationJob.objects.create(shop=shop, **defaults)


# ── Reserve / consume / release tests ────────────────────────────────────


class TestReserveConsumeRelease:
    def test_reserve_basic(self, shop, starter_subscription):
        result = reserve(shop, "store_generations", 1)
        assert result.allowed is True
        counter = UsageCounter.objects.get(shop=shop)
        assert counter.reserved_store_generations == 1

    def test_reserve_agency_plan(self, shop):
        Subscription.objects.create(
            shop=shop,
            shopify_subscription_gid="gid://shopify/AppSubscription/456",
            plan=Plan.AGENCY,
            status="active",
        )
        result = reserve(shop, "store_generations", 10)
        assert result.allowed is True

    def test_reserve_agency_limit_50(self, shop):
        Subscription.objects.create(
            shop=shop,
            shopify_subscription_gid="gid://shopify/AppSubscription/789",
            plan=Plan.AGENCY,
            status="active",
        )
        for _ in range(50):
            result = reserve(shop, "store_generations", 1)
            assert result.allowed is True
        result = reserve(shop, "store_generations", 1)
        assert result.allowed is False

    def test_reserve_exceeds_limit(self, shop, starter_subscription):
        # Starter limit for store_generations
        from apps.billing.plans import get_plan_limits

        limits = get_plan_limits("starter")
        max_gen = limits.get("store_generations", 3)

        # Reserve up to the limit
        for _ in range(max_gen):
            result = reserve(shop, "store_generations", 1)
            assert result.allowed is True

        # Next one should fail
        result = reserve(shop, "store_generations", 1)
        assert result.allowed is False
        assert "PLAN_LIMIT_REACHED" in result.message

    def test_reserve_partial_exceeds(self, shop, starter_subscription):
        from apps.billing.plans import get_plan_limits

        limits = get_plan_limits("starter")
        max_gen = limits.get("store_generations", 3)

        # Reserve all but one
        for _ in range(max_gen - 1):
            reserve(shop, "store_generations", 1)

        # Try to reserve 2 — should fail
        result = reserve(shop, "store_generations", 2)
        assert result.allowed is False

    def test_consume_basic(self, shop, starter_subscription):
        reserve(shop, "store_generations", 1)
        consume(shop, "store_generations", 1)
        counter = UsageCounter.objects.get(shop=shop)
        assert counter.store_generations == 1
        assert counter.reserved_store_generations == 0

    def test_release_basic(self, shop, starter_subscription):
        reserve(shop, "store_generations", 1)
        release(shop, "store_generations", 1)
        counter = UsageCounter.objects.get(shop=shop)
        assert counter.reserved_store_generations == 0

    def test_release_does_not_go_negative(self, shop, starter_subscription):
        release(shop, "store_generations", 5)
        counter = UsageCounter.objects.get(shop=shop)
        assert counter.reserved_store_generations == 0

    def test_reserve_invalid_resource(self, shop):
        with pytest.raises(ValueError, match="Unknown resource"):
            reserve(shop, "invalid_resource", 1)


# ── Pipeline integration tests ───────────────────────────────────────────


class TestPipelineLimitsIntegration:
    @patch("apps.generator.tasks._execute_step", return_value={"ok": True})
    def test_job_success_consumes_usage(self, mock_step, shop, starter_subscription):
        job = _make_job(shop)
        result = execute_job(str(job.id))

        assert result["status"] == JobStatus.SUCCEEDED
        counter = UsageCounter.objects.get(shop=shop)
        assert counter.store_generations == 1
        assert counter.reserved_store_generations == 0

    @patch("apps.generator.tasks._execute_step", return_value=None)
    def test_job_failure_releases_usage(self, mock_step, shop, starter_subscription):
        from apps.generator.errors import ImportSourceBlocked

        job = _make_job(shop)
        JobStep.objects.create(job=job, name="import", status=StepStatus.PENDING)
        JobStep.objects.create(job=job, name="research", status=StepStatus.PENDING)

        def failing_step(job, step):
            if step.name == "import":
                raise ImportSourceBlocked()
            return None

        mock_step.side_effect = failing_step
        result = execute_job(str(job.id))

        assert result["error"] == "IMPORT_SOURCE_BLOCKED"
        counter = UsageCounter.objects.get(shop=shop)
        assert counter.store_generations == 0
        assert counter.reserved_store_generations == 0

    @patch("apps.generator.tasks._execute_step", return_value=None)
    def test_plan_limit_reached_blocks_job(self, mock_step, shop, starter_subscription):
        from apps.billing.plans import get_plan_limits

        limits = get_plan_limits("starter")
        max_gen = limits.get("store_generations", 3)

        # Exhaust the limit
        for _ in range(max_gen):
            reserve(shop, "store_generations", 1)

        job = _make_job(shop)
        result = execute_job(str(job.id))

        assert result["error"] == "PLAN_LIMIT_REACHED"
        job.refresh_from_db()
        assert job.status == JobStatus.FAILED

    @patch("apps.generator.tasks._execute_step", return_value={"ok": True})
    def test_resume_does_not_double_reserve(self, mock_step, shop, starter_subscription):
        job = _make_job(shop)
        job.started_at = timezone.now()
        job.save(update_fields=["started_at"])

        # Create one succeeded step, one pending
        JobStep.objects.create(job=job, name="import", status=StepStatus.SUCCEEDED)
        JobStep.objects.create(job=job, name="research", status=StepStatus.PENDING)

        result = execute_job(str(job.id))
        assert result["status"] == JobStatus.SUCCEEDED

        # Should have consumed exactly 1, not 2
        counter = UsageCounter.objects.get(shop=shop)
        assert counter.store_generations == 1


# ── Usage summary tests ──────────────────────────────────────────────────


class TestUsageSummary:
    def test_usage_summary_structure(self, shop, starter_subscription):
        summary = get_usage_summary(shop)

        assert summary["plan"] == "starter"
        assert "period_start" in summary
        assert "limits" in summary
        assert "usage" in summary
        assert "store_generations" in summary["usage"]
        assert "ai_images" in summary["usage"]
        assert "live_pages" in summary["usage"]

    def test_usage_summary_after_consume(self, shop, starter_subscription):
        reserve(shop, "store_generations", 1)
        consume(shop, "store_generations", 1)

        summary = get_usage_summary(shop)
        usage = summary["usage"]["store_generations"]
        assert usage["consumed"] == 1
        assert usage["reserved"] == 0

    def test_usage_summary_after_reserve(self, shop, starter_subscription):
        reserve(shop, "store_generations", 2)

        summary = get_usage_summary(shop)
        usage = summary["usage"]["store_generations"]
        assert usage["consumed"] == 0
        assert usage["reserved"] == 2

    def test_usage_summary_no_subscription_defaults_starter(self, shop):
        summary = get_usage_summary(shop)
        assert summary["plan"] == "starter"
