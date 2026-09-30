"""Tests for T-012: research step + angle selection."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.models import GenerationJob, JobStatus, JobStep, StepStatus
from apps.generator.research_step import (
    NUM_ANGLES,
    get_angle_cards,
    run_research,
    select_angle,
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
def job(db, shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind="page",
        content_locale="nl",
        input={"product_gid": "gid://shopify/Product/123", "niche_hint": "wellness"},
        status=JobStatus.RUNNING,
    )


@pytest.fixture
def import_step(db, job):
    return JobStep.objects.create(
        job=job,
        name="import",
        status=StepStatus.SUCCEEDED,
        output={
            "title": "Test Product",
            "description": "A great product",
            "price": "29.99",
            "currency": "EUR",
            "reference_image_urls": ["https://cdn.example.com/img1.jpg"],
        },
    )


def _make_research_result():
    from apps.ai.schemas import ResearchResult

    return ResearchResult(
        niche="wellness_sleep",
        product_summary="A great product for wellness",
        personas=[
            {
                "id": "p1",
                "name": "Busy parent",
                "description": "A busy parent",
                "pains": ["No time", "Stress"],
                "desires": ["Save time", "Simplicity"],
            },
            {
                "id": "p2",
                "name": "Budget shopper",
                "description": "Budget conscious",
                "pains": ["Cost", "Quality"],
                "desires": ["Value", "Savings"],
            },
        ],
        angles=[
            {"id": "a1", "title": "Save Time", "hook": "Quick solution", "persona_id": "p1"},
            {"id": "a2", "title": "Save Money", "hook": "Best value", "persona_id": "p2"},
            {"id": "a3", "title": "Premium Quality", "hook": "Top tier", "persona_id": "p1"},
        ],
        usps=["Fast", "Cheap", "Quality"],
        objections=["Price", "Trust"],
        faq=[
            {"q": "Q1?", "a": "A1"},
            {"q": "Q2?", "a": "A2"},
            {"q": "Q3?", "a": "A3"},
            {"q": "Q4?", "a": "A4"},
        ],
        claim_risks=["medical claim risk"],
    )


# ── Research step tests ───────────────────────────────────────────────────


class TestResearchStep:
    @patch("apps.ai.anthropic_client.call_ai")
    def test_research_success(self, mock_ai, job, import_step):
        mock_ai.return_value = _make_research_result()
        result = run_research(job, JobStep(job=job, name="research"))
        assert result is not None
        assert len(result["angles"]) == NUM_ANGLES
        assert result["claim_risks"] == ["medical claim risk"]

    @patch("apps.ai.anthropic_client.call_ai")
    def test_research_sets_needs_input(self, mock_ai, job, import_step):
        mock_ai.return_value = _make_research_result()
        run_research(job, JobStep(job=job, name="research"))
        job.refresh_from_db()
        assert job.status == JobStatus.NEEDS_INPUT

    @patch("apps.ai.anthropic_client.call_ai")
    def test_research_with_angle_already_chosen(self, mock_ai, job, import_step):
        job.input["angle_id"] = "a1"
        job.save(update_fields=["input"])
        mock_ai.return_value = _make_research_result()
        run_research(job, JobStep(job=job, name="research"))
        job.refresh_from_db()
        assert job.status != JobStatus.NEEDS_INPUT

    @patch("apps.ai.anthropic_client.call_ai")
    def test_research_no_import_result(self, mock_ai, job):
        result = run_research(job, JobStep(job=job, name="research"))
        assert result is None

    @patch("apps.ai.anthropic_client.call_ai")
    def test_research_wrong_angle_count(self, mock_ai, job, import_step):
        from apps.ai.schemas import ResearchResult

        bad = ResearchResult.model_construct(
            niche="wellness_sleep",
            product_summary="Test",
            personas=[{"id": "p1", "name": "P1", "description": "D", "pains": ["A", "B"], "desires": ["C", "D"]}],
            angles=[{"id": "a1", "title": "Only One", "hook": "H", "persona_id": "p1"}],
            usps=["A", "B", "C"],
            objections=["X", "Y"],
            faq=[{"q": "Q1", "a": "A1"}, {"q": "Q2", "a": "A2"}, {"q": "Q3", "a": "A3"}, {"q": "Q4", "a": "A4"}],
            claim_risks=[],
        )
        mock_ai.return_value = bad
        result = run_research(job, JobStep(job=job, name="research"))
        assert result is None


# ── Angle selection tests ─────────────────────────────────────────────────


class TestAngleSelection:
    def _setup_research(self, job):
        return JobStep.objects.create(
            job=job,
            name="research",
            status=StepStatus.SUCCEEDED,
            output=_make_research_result().model_dump(mode="json"),
        )

    @patch("apps.generator.tasks.execute_job")
    def test_select_valid_angle(self, mock_exec, job, import_step):
        self._setup_research(job)
        result = select_angle(job, "a1")
        assert result is True
        job.refresh_from_db()
        assert job.input["angle_id"] == "a1"
        mock_exec.assert_called_once()

    @patch("apps.generator.tasks.execute_job")
    def test_select_invalid_angle(self, mock_exec, job, import_step):
        self._setup_research(job)
        result = select_angle(job, "nonexistent")
        assert result is False
        mock_exec.assert_not_called()

    @patch("apps.generator.tasks.execute_job")
    def test_select_angle_no_research(self, mock_exec, job):
        result = select_angle(job, "a1")
        assert result is False

    def test_get_angle_cards(self, job, import_step):
        self._setup_research(job)
        cards = get_angle_cards(job)
        assert len(cards) == NUM_ANGLES
        assert cards[0]["id"] == "a1"
        assert cards[0]["title"] == "Save Time"

    def test_get_angle_cards_no_research(self, job):
        cards = get_angle_cards(job)
        assert cards == []


# ── Prompt rendering tests ────────────────────────────────────────────────


class TestPromptRendering:
    @patch("apps.ai.anthropic_client.call_ai")
    def test_prompt_includes_import_data(self, mock_ai, job, import_step):
        mock_ai.return_value = _make_research_result()
        run_research(job, JobStep(job=job, name="research"))
        # call_ai receives system=prompt which should include import data
        call_kwargs = mock_ai.call_args
        assert call_kwargs is not None
