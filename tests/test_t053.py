"""Tests for T-053: translate_page + translation status."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.models import GenerationJob, JobKind, JobStatus, JobStep, Page, StepStatus
from apps.generator.translate_step import (
    get_translation_status,
    translate_page,
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
    j = GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type="pdp",
        content_locale="nl",
        input={"angle_id": "a1"},
        status=JobStatus.SUCCEEDED,
        idempotency_key="test-job-1",
    )
    JobStep.objects.create(
        job=j,
        name="import",
        status=StepStatus.SUCCEEDED,
        output={"title": "Test", "price": "29.99", "specs": {"Color": "Blue"}},
    )
    JobStep.objects.create(
        job=j,
        name="research",
        status=StepStatus.SUCCEEDED,
        output={
            "niche": "wellness",
            "chosen_angle": {"id": "a1", "title": "Angle"},
            "angles": [{"id": "a1", "title": "Angle"}],
        },
    )
    return j


@pytest.fixture
def page(db, shop, job):
    return Page.objects.create(
        shop=shop,
        job=job,
        page_type="pdp",
        title="Test",
        content_locale="nl",
        sections={
            "nl": {
                "sections": [
                    {"type": "hero", "headline": "Product", "subheadline": "Best", "cta_label": "Koop"},
                    {"type": "benefits", "title": "Waarom", "items": ["A", "B"]},
                ],
                "seo_title": "Test SEO",
                "seo_description": "Test desc",
            }
        },
        version=1,
    )


class TestTranslationStatus:
    @patch("apps.generator.translate_step.get_published_shop_locales")
    def test_status_no_translations(self, mock_locales, page):
        mock_locales.return_value = ["nl", "en", "de"]
        status = get_translation_status(page)
        assert status["source_locale"] == "nl"
        assert status["translated"] == []
        assert sorted(status["available"]) == ["de", "en"]

    @patch("apps.generator.translate_step.get_published_shop_locales")
    def test_status_with_translation(self, mock_locales, page):
        mock_locales.return_value = ["nl", "en", "de"]
        page.sections["en"] = {"sections": [], "seo_title": "", "seo_description": ""}
        page.save(update_fields=["sections"])

        status = get_translation_status(page)
        assert "en" in status["translated"]
        assert "en" not in status["available"]
        assert "de" in status["available"]

    @patch("apps.generator.translate_step.get_published_shop_locales")
    def test_status_only_supported_locales(self, mock_locales, page):
        mock_locales.return_value = ["nl", "en", "de", "fr"]
        status = get_translation_status(page)
        assert "fr" not in status["available"]


class TestTranslatePage:
    @patch("apps.generator.translate_step.get_published_shop_locales")
    @patch("apps.ai.anthropic_client.call_ai")
    def test_translate_success(self, mock_ai, mock_locales, page):
        mock_locales.return_value = ["nl", "en", "de"]

        # Mock SectionsPayload
        mock_payload = MagicMock()
        mock_payload.sections = [
            MagicMock(model_dump=lambda: {"type": "hero", "headline": "Great Product"}),
            MagicMock(model_dump=lambda: {"type": "benefits", "title": "Why", "items": ["A"]}),
        ]
        mock_payload.seo_title = "Great Product SEO"
        mock_payload.seo_description = "Great product description"
        mock_ai.return_value = mock_payload

        ok, msg, output = translate_page(page, "en")
        assert ok is True
        assert output["target_locale"] == "en"
        assert "en" in page.sections

    @patch("apps.ai.anthropic_client.call_ai")
    def test_translate_unsupported_locale(self, mock_ai, page):
        ok, msg, output = translate_page(page, "fr")
        assert ok is False
        assert "Unsupported" in msg

    @patch("apps.ai.anthropic_client.call_ai")
    def test_translate_same_locale(self, mock_ai, page):
        ok, msg, output = translate_page(page, "nl")
        assert ok is False
        assert "same as source" in msg

    @patch("apps.generator.translate_step.get_published_shop_locales")
    @patch("apps.ai.anthropic_client.call_ai")
    def test_translate_runs_compliance(self, mock_ai, mock_locales, page):
        """Translation runs compliance check for the target language."""
        mock_locales.return_value = ["nl", "en", "de"]
        mock_payload = MagicMock()
        mock_payload.sections = [
            MagicMock(model_dump=lambda: {"type": "hero", "headline": "Great"}),
            MagicMock(model_dump=lambda: {"type": "cta", "headline": "Buy now", "button_label": "Go"}),
        ]
        mock_payload.seo_title = "SEO"
        mock_payload.seo_description = "Desc"
        mock_ai.return_value = mock_payload

        ok, msg, output = translate_page(page, "de")
        assert ok is True
        assert "compliance_score" in output

    @patch("apps.generator.translate_step.get_published_shop_locales")
    @patch("apps.ai.anthropic_client.call_ai")
    def test_translate_metaobject_handle(self, mock_ai, mock_locales, page):
        """Metaobject handle has -<lang> suffix (03 §5.1)."""
        mock_locales.return_value = ["nl", "en", "de"]
        mock_payload = MagicMock()
        mock_payload.sections = [
            MagicMock(model_dump=lambda: {"type": "hero", "headline": "Test"}),
            MagicMock(model_dump=lambda: {"type": "cta", "headline": "Buy", "button_label": "Go"}),
        ]
        mock_payload.seo_title = "SEO"
        mock_payload.seo_description = "Desc"
        mock_ai.return_value = mock_payload

        ok, msg, output = translate_page(page, "en")
        assert ok is True
        assert output["metaobject_handle"].endswith("-en")

    @patch("apps.generator.translate_step.get_published_shop_locales")
    @patch("apps.ai.anthropic_client.call_ai")
    def test_translate_preserves_source(self, mock_ai, mock_locales, page):
        """Source language sections are preserved."""
        mock_locales.return_value = ["nl", "en", "de"]
        mock_payload = MagicMock()
        mock_payload.sections = [
            MagicMock(model_dump=lambda: {"type": "hero", "headline": "New"}),
            MagicMock(model_dump=lambda: {"type": "cta", "headline": "Buy", "button_label": "Go"}),
        ]
        mock_payload.seo_title = "SEO"
        mock_payload.seo_description = "Desc"
        mock_ai.return_value = mock_payload

        ok, msg, output = translate_page(page, "en")
        assert ok is True
        # Source nl still exists
        assert "nl" in page.sections
        assert "en" in page.sections
