"""Tests for T-010: GenerationJob, JobStep, AiCall, Page models, orchestration, error codes."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.errors import (
    AiBudgetExceeded,
    AiProviderError,
    AiSchemaInvalid,
    ComplianceBlocked,
    GeneratorError,
    GpsrIncomplete,
    ImportNotFound,
    ImportSourceBlocked,
    PlanLimitReached,
    check_job_budget,
)
from apps.generator.models import (
    AiCall,
    GenerationJob,
    JobKind,
    JobStatus,
    JobStep,
    Page,
    PageType,
    StepStatus,
)
from apps.generator.tasks import (
    PAGE_STEP_ORDER,
    accumulate_job_cost,
    execute_job,
    get_pending_steps,
    update_job_from_steps,
)

JOB_INPUT = {
    "kind": "page",
    "product_gid": "gid://shopify/Product/1",
    "page_type": "pdp",
    "content_locale": "nl",
    "style_preset": "clean",
}


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
def page_job(shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type=PageType.PDP,
        content_locale="nl",
        input=JOB_INPUT,
        idempotency_key="test-key-001",
    )


@pytest.fixture
def store_job(shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.STORE,
        content_locale="nl",
        input={"kind": "store", "content_locale": "nl", "style_preset": "clean"},
        idempotency_key="store-key-001",
    )


# ── Model tests ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGenerationJobModel:
    def test_create_page_job(self, shop):
        job = GenerationJob.objects.create(
            shop=shop,
            kind="page",
            page_type="pdp",
            content_locale="nl",
            input={"kind": "page"},
            idempotency_key="key-1",
        )
        assert job.status == "queued"
        assert job.ai_cost_usd == Decimal("0")
        assert str(job) == "page/pdp (queued) — test-store.myshopify.com"

    def test_idempotency_key_unique_per_shop(self, shop):
        GenerationJob.objects.create(
            shop=shop,
            kind="page",
            page_type="pdp",
            content_locale="nl",
            input={},
            idempotency_key="key-1",
        )
        with pytest.raises(IntegrityError):
            GenerationJob.objects.create(
                shop=shop,
                kind="page",
                page_type="pdp",
                content_locale="nl",
                input={},
                idempotency_key="key-1",
            )

    def test_idempotency_key_different_shops(self, shop, db):
        GenerationJob.objects.create(
            shop=shop,
            kind="page",
            page_type="pdp",
            content_locale="nl",
            input={},
            idempotency_key="key-1",
        )
        shop2 = Shop.objects.create(
            domain="other-store.myshopify.com",
            shopify_gid="gid://shopify/Shop/456",
            access_token_encrypted=encrypt_token("tok"),
            refresh_token_encrypted=encrypt_token("ref"),
            currency_code="EUR",
        )
        job2 = GenerationJob.objects.create(
            shop=shop2,
            kind="page",
            page_type="pdp",
            content_locale="nl",
            input={},
            idempotency_key="key-1",
        )
        assert job2 is not None

    def test_child_jobs(self, shop):
        parent = GenerationJob.objects.create(
            shop=shop,
            kind="store",
            content_locale="nl",
            input={},
            idempotency_key="store-1",
        )
        child = GenerationJob.objects.create(
            shop=shop,
            kind="page",
            page_type="pdp",
            content_locale="nl",
            input={},
            idempotency_key="child-1",
            parent=parent,
        )
        assert child.parent == parent
        assert parent.children.count() == 1


@pytest.mark.django_db
class TestJobStepModel:
    def test_create_step(self, page_job):
        step = JobStep.objects.create(
            job=page_job,
            name="import",
            status=StepStatus.PENDING,
        )
        assert step.attempt == 0
        assert step.ai_cost_usd == Decimal("0")
        assert str(step) == "import (pending) — attempt 0"

    def test_unique_job_step_name(self, page_job):
        JobStep.objects.create(job=page_job, name="import", status="pending")
        with pytest.raises(IntegrityError):
            JobStep.objects.create(job=page_job, name="import", status="pending")

    def test_steps_can_be_different_jobs(self, page_job, shop):
        other_job = GenerationJob.objects.create(
            shop=shop,
            kind="page",
            page_type="landing",
            content_locale="nl",
            input={},
            idempotency_key="other-1",
        )
        JobStep.objects.create(job=page_job, name="import", status="pending")
        JobStep.objects.create(job=other_job, name="import", status="pending")
        assert JobStep.objects.filter(name="import").count() == 2


@pytest.mark.django_db
class TestAiCallModel:
    def test_create_call(self, shop):
        call = AiCall.objects.create(
            shop=shop,
            purpose="research",
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=50,
            cost_usd=Decimal("0.01"),
            duration_ms=1500,
            success=True,
        )
        assert call.success is True
        assert "research" in str(call)

    def test_call_without_step(self, shop):
        call = AiCall.objects.create(
            shop=shop,
            purpose="palette",
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            cost_usd=Decimal("0.005"),
        )
        assert call.step is None


@pytest.mark.django_db
class TestPageModel:
    def test_create_page(self, shop):
        page = Page.objects.create(
            shop=shop,
            page_type="pdp",
            title="Test Product",
            content_locale="nl",
        )
        assert page.status == "draft"
        assert page.version == 0
        assert page.compliance_score == 0

    def test_sections_per_locale(self, shop):
        page = Page.objects.create(
            shop=shop,
            page_type="pdp",
            title="Test",
            content_locale="nl",
            sections={"nl": {"sections": [], "seo_title": "Test"}},
        )
        page.refresh_from_db()
        assert "nl" in page.sections


# ── Error code tests ──────────────────────────────────────────────────────


class TestErrorCodes:
    def test_all_error_codes(self):
        """Every error has a code and merchant message."""
        errors = [
            ImportNotFound(),
            ImportSourceBlocked(),
            AiSchemaInvalid(),
            AiProviderError(),
            AiBudgetExceeded(),
            ComplianceBlocked(),
            GpsrIncomplete(),
            PlanLimitReached(),
        ]
        for err in errors:
            assert err.code
            assert err.merchant_message

    def test_custom_code_override(self):
        err = AiBudgetExceeded(code="CUSTOM")
        assert err.code == "CUSTOM"

    def test_base_class(self):
        assert issubclass(AiBudgetExceeded, GeneratorError)

    def test_check_job_budget_under(self):
        """Cost below budget → no exception."""
        check_job_budget(Decimal("1.50"))

    def test_check_job_budget_at(self):
        """Cost at budget → exception."""
        with pytest.raises(AiBudgetExceeded):
            check_job_budget(Decimal("2.00"))

    def test_check_job_budget_over(self):
        """Cost over budget → exception."""
        with pytest.raises(AiBudgetExceeded):
            check_job_budget(Decimal("2.50"))


# ── Orchestration tests ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestGetPendingSteps:
    def test_page_job_creates_all_steps(self, page_job):
        steps = get_pending_steps(page_job)
        names = [s.name for s in steps]
        assert names == PAGE_STEP_ORDER

    def test_store_job_only_import_research(self, store_job):
        steps = get_pending_steps(store_job)
        names = [s.name for s in steps]
        assert names == ["import", "research"]

    def test_skips_succeeded_steps(self, page_job):
        JobStep.objects.create(job=page_job, name="import", status=StepStatus.SUCCEEDED)
        JobStep.objects.create(job=page_job, name="research", status=StepStatus.SUCCEEDED)
        steps = get_pending_steps(page_job)
        names = [s.name for s in steps]
        assert names == ["copy", "images", "compliance_check", "layout", "publish"]

    def test_skips_skipped_steps(self, page_job):
        JobStep.objects.create(job=page_job, name="import", status=StepStatus.SKIPPED)
        steps = get_pending_steps(page_job)
        names = [s.name for s in steps]
        assert "import" not in names

    def test_failed_steps_included(self, page_job):
        JobStep.objects.create(job=page_job, name="import", status=StepStatus.FAILED)
        steps = get_pending_steps(page_job)
        names = [s.name for s in steps]
        assert "import" in names

    def test_get_or_create_is_idempotent(self, page_job):
        """Calling twice doesn't create duplicate steps."""
        steps1 = get_pending_steps(page_job)
        steps2 = get_pending_steps(page_job)
        assert len(steps1) == len(steps2)
        assert JobStep.objects.filter(job=page_job).count() == len(PAGE_STEP_ORDER)


@pytest.mark.django_db
class TestUpdateJobFromSteps:
    def test_running_step(self, page_job):
        JobStep.objects.create(job=page_job, name="import", status=StepStatus.RUNNING)
        update_job_from_steps(page_job)
        page_job.refresh_from_db()
        assert page_job.status == JobStatus.RUNNING
        assert page_job.current_step == "import"

    def test_failed_step(self, page_job):
        JobStep.objects.create(job=page_job, name="import", status=StepStatus.FAILED)
        update_job_from_steps(page_job)
        page_job.refresh_from_db()
        assert page_job.status == JobStatus.FAILED

    def test_all_succeeded(self, page_job):
        for name in PAGE_STEP_ORDER:
            JobStep.objects.create(job=page_job, name=name, status=StepStatus.SUCCEEDED)
        update_job_from_steps(page_job)
        page_job.refresh_from_db()
        assert page_job.status == JobStatus.SUCCEEDED
        assert page_job.finished_at is not None

    def test_mixed_statuses(self, page_job):
        JobStep.objects.create(job=page_job, name="import", status=StepStatus.SUCCEEDED)
        JobStep.objects.create(job=page_job, name="research", status=StepStatus.PENDING)
        update_job_from_steps(page_job)
        page_job.refresh_from_db()
        assert page_job.status == JobStatus.QUEUED
        assert page_job.current_step == "research"


@pytest.mark.django_db
class TestAccumulateJobCost:
    def test_sums_step_costs(self, page_job):
        JobStep.objects.create(job=page_job, name="import", ai_cost_usd=Decimal("0.01"))
        JobStep.objects.create(job=page_job, name="research", ai_cost_usd=Decimal("0.05"))
        accumulate_job_cost(page_job)
        page_job.refresh_from_db()
        assert page_job.ai_cost_usd == Decimal("0.06")

    def test_no_steps(self, page_job):
        accumulate_job_cost(page_job)
        page_job.refresh_from_db()
        assert page_job.ai_cost_usd == Decimal("0")


# ── run_job orchestration tests ───────────────────────────────────────────


@pytest.mark.django_db
class TestRunJob:
    @patch("apps.generator.tasks._execute_step")
    def test_runs_pending_steps(self, mock_execute, page_job):
        """run_job executes all pending steps."""
        mock_execute.return_value = None
        result = execute_job(str(page_job.id))
        assert result["status"] == JobStatus.SUCCEEDED
        page_job.refresh_from_db()
        assert page_job.status == JobStatus.SUCCEEDED
        assert page_job.current_step is None

    @patch("apps.generator.tasks._execute_step")
    def test_skips_succeeded_steps(self, mock_execute, page_job):
        """Already-succeeded steps are not re-run."""
        mock_execute.return_value = None
        JobStep.objects.create(job=page_job, name="import", status=StepStatus.SUCCEEDED)
        result = execute_job(str(page_job.id))
        assert result["status"] == JobStatus.SUCCEEDED

    @patch("apps.generator.tasks._execute_step")
    def test_failed_step_stops_job(self, mock_execute, page_job):
        """A failed step stops the job."""
        mock_execute.side_effect = ImportError("test error")
        result = execute_job(str(page_job.id))
        assert result["error"] == "UNKNOWN_ERROR"
        page_job.refresh_from_db()
        assert page_job.status == JobStatus.FAILED

    @patch("apps.generator.tasks._execute_step")
    def test_budget_exceeded(self, mock_execute, page_job):
        """Budget exceeded → job fails with AI_BUDGET_EXCEEDED."""
        page_job.ai_cost_usd = Decimal("2.00")
        page_job.save(update_fields=["ai_cost_usd"])
        result = execute_job(str(page_job.id))
        assert result["error"] == "AI_BUDGET_EXCEEDED"
        page_job.refresh_from_db()
        assert page_job.error_code == "AI_BUDGET_EXCEEDED"

    @patch("apps.generator.tasks._execute_step")
    def test_job_not_found(self, mock_execute):
        result = execute_job("00000000-0000-0000-0000-000000000000")
        assert result["error"] == "job_not_found"

    @patch("apps.generator.tasks._execute_step")
    def test_completed_job_skipped(self, mock_execute, page_job):
        page_job.status = JobStatus.SUCCEEDED
        page_job.save(update_fields=["status"])
        result = execute_job(str(page_job.id))
        assert result["status"] == JobStatus.SUCCEEDED

    @patch("apps.generator.tasks._execute_step")
    def test_cancelled_job_skipped(self, mock_execute, page_job):
        page_job.status = JobStatus.CANCELLED
        page_job.save(update_fields=["status"])
        result = execute_job(str(page_job.id))
        assert result["status"] == JobStatus.CANCELLED

    @patch("apps.generator.tasks._execute_step")
    def test_attempts_incremented(self, mock_execute, page_job):
        """Step attempts are incremented on each run."""
        mock_execute.return_value = None
        execute_job(str(page_job.id))
        step = JobStep.objects.get(job=page_job, name="import")
        assert step.attempt == 1

    @patch("apps.generator.tasks._execute_step")
    def test_step_output_stored(self, mock_execute, page_job):
        """Step output is stored as checkpoint."""
        mock_execute.return_value = {"product_gid": "gid://shopify/Product/1"}
        execute_job(str(page_job.id))
        step = JobStep.objects.get(job=page_job, name="import")
        assert step.output == {"product_gid": "gid://shopify/Product/1"}

    @patch("apps.generator.tasks._execute_step")
    def test_store_job_only_two_steps(self, mock_execute, store_job):
        """Store job runs only import + research."""
        mock_execute.return_value = None
        result = execute_job(str(store_job.id))
        assert result["status"] == JobStatus.SUCCEEDED
        steps = JobStep.objects.filter(job=store_job)
        assert steps.count() == 2

    @patch("apps.generator.tasks._execute_step")
    def test_step_timestamps_set(self, mock_execute, page_job):
        """Steps get started_at and finished_at timestamps."""
        mock_execute.return_value = None
        execute_job(str(page_job.id))
        step = JobStep.objects.get(job=page_job, name="import")
        assert step.started_at is not None
        assert step.finished_at is not None
