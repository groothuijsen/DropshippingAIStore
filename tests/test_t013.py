"""Tests for T-013: copy step + guardrails + language detection + Page creation."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.copy_step import SECTION_ORDER, get_section_order, run_copy
from apps.generator.language_detection import detect_language
from apps.generator.models import GenerationJob, JobStatus, JobStep, Page, PageStatus, StepStatus


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
        page_type="pdp",
        content_locale="nl",
        input={
            "product_gid": "gid://shopify/Product/123",
            "niche_hint": "wellness",
            "angle_id": "a1",
        },
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
            "specs": {"Material": "Cotton", "Size": "M", "Weight": "200g"},
        },
    )


@pytest.fixture
def research_step(db, job):
    return JobStep.objects.create(
        job=job,
        name="research",
        status=StepStatus.SUCCEEDED,
        output={
            "niche": "wellness_sleep",
            "product_summary": "Test",
            "personas": [],
            "angles": [
                {"id": "a1", "title": "Save Time", "hook": "Quick", "persona_id": "p1"},
                {"id": "a2", "title": "Save Money", "hook": "Value", "persona_id": "p2"},
                {"id": "a3", "title": "Premium", "hook": "Top", "persona_id": "p1"},
            ],
            "usps": [],
            "objections": [],
            "faq": [],
            "claim_risks": [],
            "chosen_angle": {"id": "a1", "title": "Save Time", "hook": "Quick", "persona_id": "p1"},
        },
    )


def _make_sections_payload():
    from apps.ai.schemas import SectionsPayload

    return SectionsPayload.model_construct(
        locale="nl",
        page_type="pdp",
        seo_title="Test Product - Bespaar Tijd",
        seo_description="Ontdek hoe dit product je tijd bespaart. Bestel nu!",
        sections=[
            {"type": "hero", "headline": "Bespaar Tijd", "subheadline": "Met ons product", "cta_label": "Koop nu"},
            {"type": "benefits", "title": "Voordelen", "items": [{"title": "Snel", "text": "Direct resultaat"}]},
            {"type": "how_it_works", "title": "Hoe het werkt", "steps": [{"title": "Stap 1", "text": "Doe dit"}]},
            {"type": "specs", "rows": [{"label": "Material", "value": "Cotton"}]},
            {
                "type": "comparison",
                "ours_label": "Ons",
                "other_label": "Ander",
                "rows": [{"feature": "Snel", "ours": True, "other": False}],
            },
            {"type": "faq", "items": [{"question": "Wat is dit?", "answer": "Een product"}]},
            {"type": "cta", "headline": "Klaar om te kopen?", "subheadline": "Bestel nu!", "button_label": "Koop"},
        ],
    )


# ── Section order tests ───────────────────────────────────────────────────


class TestSectionOrder:
    def test_pdp_order(self):
        order = get_section_order("pdp", {"specs": {"a": "1", "b": "2"}}, "2 jaar garantie")
        assert order == ["hero", "benefits", "how_it_works", "specs", "comparison", "faq", "guarantee", "cta"]

    def test_pdp_no_specs(self):
        order = get_section_order("pdp", {"specs": {"a": "1"}}, "garantie")
        assert "specs" not in order

    def test_pdp_no_guarantee(self):
        order = get_section_order("pdp", {"specs": {"a": "1", "b": "2"}}, "")
        assert "guarantee" not in order

    def test_landing_order(self):
        order = get_section_order("landing", {}, "")
        assert "guarantee" not in order
        assert "hero" in order

    def test_all_page_types_have_orders(self):
        for pt in ["pdp", "landing", "advertorial", "listicle", "home", "about"]:
            assert pt in SECTION_ORDER


# ── Language detection tests ──────────────────────────────────────────────


class TestLanguageDetection:
    def test_detect_dutch(self):
        text = "Dit is een geweldig product dat je tijd bespaart en geld bespaart"
        assert detect_language(text) == "nl"

    def test_detect_english(self):
        text = "This is a great product that saves you time and money with our service"
        assert detect_language(text) == "en"

    def test_detect_german(self):
        text = "Dies ist ein großartiges Produkt das Ihnen Zeit spart und hilft"
        assert detect_language(text) == "de"

    def test_detect_empty(self):
        assert detect_language("") is None

    def test_detect_none(self):
        assert detect_language("xyz abc def") is None


# ── Copy step tests ───────────────────────────────────────────────────────


class TestCopyStep:
    @patch("apps.ai.anthropic_client.call_ai")
    def test_copy_success(self, mock_ai, job, import_step, research_step):
        mock_ai.return_value = _make_sections_payload()
        result = run_copy(job, JobStep(job=job, name="copy"))
        assert result is not None
        assert result["seo_title"] == "Test Product - Bespaar Tijd"
        assert "page_id" in result

    @patch("apps.ai.anthropic_client.call_ai")
    def test_copy_creates_page(self, mock_ai, job, import_step, research_step):
        mock_ai.return_value = _make_sections_payload()
        result = run_copy(job, JobStep(job=job, name="copy"))
        assert result is not None
        page_id = result["page_id"]
        page = Page.objects.get(id=page_id)
        assert page.status == PageStatus.DRAFT
        assert page.page_type == "pdp"
        assert page.content_locale == "nl"

    @patch("apps.ai.anthropic_client.call_ai")
    def test_copy_no_import(self, mock_ai, job, research_step):
        result = run_copy(job, JobStep(job=job, name="copy"))
        assert result is None

    @patch("apps.ai.anthropic_client.call_ai")
    def test_copy_no_research(self, mock_ai, job, import_step):
        result = run_copy(job, JobStep(job=job, name="copy"))
        assert result is None

    @patch("apps.ai.anthropic_client.call_ai")
    def test_copy_no_chosen_angle(self, mock_ai, job, import_step, research_step):
        research_step.output.pop("chosen_angle", None)
        research_step.save(update_fields=["output"])
        job.input.pop("angle_id", None)
        job.save(update_fields=["input"])
        result = run_copy(job, JobStep(job=job, name="copy"))
        assert result is None

    @patch("apps.ai.anthropic_client.call_ai")
    def test_copy_specs_row_filtering(self, mock_ai, job, import_step, research_step):
        payload = _make_sections_payload()
        # Add an invalid specs row
        for section in payload.sections:
            if section.get("type") == "specs":
                section["rows"].append({"label": "Invalid Key", "value": "Should be removed"})
        mock_ai.return_value = payload
        result = run_copy(job, JobStep(job=job, name="copy"))
        assert result is not None
        # Find specs section in output
        for section in result["sections"]:
            if section.get("type") == "specs":
                labels = [r["label"] for r in section["rows"]]
                assert "Invalid Key" not in labels
                assert "Material" in labels


# ── SEO length tests ──────────────────────────────────────────────────────


class TestSeoLength:
    def test_seo_title_max_60(self):
        from apps.ai.schemas import SectionsPayload

        payload = SectionsPayload(
            locale="nl",
            page_type="pdp",
            seo_title="X" * 60,
            seo_description="Y" * 155,
            sections=[
                {"type": "hero", "headline": "H", "subheadline": "S", "cta_label": "C"},
                {"type": "cta", "headline": "H", "subheadline": "T", "button_label": "B"},
            ],
        )
        assert len(payload.seo_title) <= 60

    def test_seo_description_max_155(self):
        from apps.ai.schemas import SectionsPayload

        payload = SectionsPayload(
            locale="nl",
            page_type="pdp",
            seo_title="Test",
            seo_description="Y" * 155,
            sections=[
                {"type": "hero", "headline": "H", "subheadline": "S", "cta_label": "C"},
                {"type": "cta", "headline": "H", "subheadline": "T", "button_label": "B"},
            ],
        )
        assert len(payload.seo_description) <= 155
