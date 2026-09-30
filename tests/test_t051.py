"""Tests for T-051: page editor + go live + archive."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.editor import (
    FIELD_LIMITS,
    get_sections_for_edit,
    recheck_page,
    update_section_field,
    validate_field_length,
)
from apps.generator.go_live import archive_page, check_can_go_live, go_live
from apps.generator.models import (
    GenerationJob,
    JobKind,
    JobStatus,
    JobStep,
    Page,
    PageStatus,
    StepStatus,
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
        mosaiq_templates_ready=False,
    )


@pytest.fixture
def job(db, shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type="pdp",
        content_locale="nl",
        input={},
        status=JobStatus.SUCCEEDED,
        idempotency_key="test-job-1",
    )


@pytest.fixture
def page(db, shop, job):
    return Page.objects.create(
        shop=shop,
        job=job,
        page_type="pdp",
        title="Test Page",
        content_locale="nl",
        sections={
            "nl": {
                "sections": [
                    {"type": "hero", "headline": "Great Product", "subheadline": "Best ever", "cta_label": "Buy"},
                    {"type": "cta", "headline": "Ready?", "subheadline": "Order now", "button_label": "Go"},
                ],
                "seo_title": "Test SEO",
                "seo_description": "Test description",
            }
        },
        images={},
        version=1,
        status=PageStatus.DRAFT,
    )


# ── Field length validation tests ─────────────────────────────────────────


class TestFieldValidation:
    def test_headline_limit(self):
        valid, _ = validate_field_length("headline", "x" * 120)
        assert valid is True

    def test_headline_over_limit(self):
        valid, msg = validate_field_length("headline", "x" * 121)
        assert valid is False
        assert "120" in msg

    def test_cta_label_limit(self):
        valid, _ = validate_field_length("cta_label", "x" * 50)
        assert valid is True
        valid, _ = validate_field_length("cta_label", "x" * 51)
        assert valid is False

    def test_unknown_field_no_limit(self):
        valid, _ = validate_field_length("unknown_field", "x" * 1000)
        assert valid is True

    def test_limits_cover_common_fields(self):
        assert "headline" in FIELD_LIMITS
        assert "seo_title" in FIELD_LIMITS
        assert "seo_description" in FIELD_LIMITS


# ── Editor tests ──────────────────────────────────────────────────────────


class TestEditor:
    def test_get_sections_for_edit(self, page):
        sections = get_sections_for_edit(page)
        assert len(sections) == 2
        assert sections[0]["type"] == "hero"
        assert "headline" in sections[0]["fields"]

    def test_update_section_field_success(self, page):
        ok, msg = update_section_field(page, 0, "headline", "New Headline")
        assert ok is True
        page.refresh_from_db()
        assert page.sections["nl"]["sections"][0]["headline"] == "New Headline"

    def test_update_section_field_too_long(self, page):
        ok, msg = update_section_field(page, 0, "headline", "x" * 200)
        assert ok is False
        assert "120" in msg

    def test_update_section_field_index_out_of_range(self, page):
        ok, msg = update_section_field(page, 99, "headline", "Test")
        assert ok is False

    def test_update_section_field_reruns_claim_check(self, page):
        """Updating with a claim should update compliance_score."""
        update_section_field(page, 0, "headline", "Dit is een duurzaam product")
        page.refresh_from_db()
        # EMPCO_GENERIC is a block → score should drop
        assert page.compliance_score < 100

    def test_recheck_page_resets_steps(self, page, job):
        JobStep.objects.create(job=job, name="compliance_check", status=StepStatus.SUCCEEDED)
        JobStep.objects.create(job=job, name="layout", status=StepStatus.SUCCEEDED)
        JobStep.objects.create(job=job, name="publish", status=StepStatus.SUCCEEDED)

        recheck_page(page)

        for step_name in ["compliance_check", "layout", "publish"]:
            step = JobStep.objects.get(job=job, name=step_name)
            assert step.status == StepStatus.PENDING


# ── Go live tests ─────────────────────────────────────────────────────────


class TestGoLive:
    def test_check_can_go_live_clean_page(self, page):
        allowed, missing = check_can_go_live(page)
        # GPSR is incomplete in test (no data), so should fail
        assert allowed is False
        assert any("GPSR" in m for m in missing)

    def test_check_can_go_live_with_blocks(self, page):
        page.sections["nl"]["sections"][0]["headline"] = "Dit geneest slapeloosheid"
        page.save(update_fields=["sections"])
        allowed, missing = check_can_go_live(page)
        assert allowed is False
        assert any("compliance" in m.lower() for m in missing)

    @patch("apps.generator.go_live._get_client")
    def test_go_live_success(self, mock_client, page):
        mock_client.return_value.close = MagicMock()
        # GPSR will fail, so mock the check
        with patch("apps.generator.go_live.check_can_go_live", return_value=(True, [])):
            result = go_live(page)
            assert result["status"] == "live"
            page.refresh_from_db()
            assert page.status == "live"

    @patch("apps.generator.go_live._get_client")
    def test_go_live_blocked(self, mock_client, page):
        mock_client.return_value.close = MagicMock()
        with pytest.raises(ValueError, match="Cannot go live"):
            go_live(page)


# ── Archive tests ─────────────────────────────────────────────────────────


class TestArchive:
    @patch("apps.generator.go_live._get_client")
    def test_archive_success(self, mock_client, page):
        mock_client.return_value.close = MagicMock()
        page.status = "live"
        page.save(update_fields=["status"])

        result = archive_page(page)
        assert result["status"] == "archived"
        page.refresh_from_db()
        assert page.status == "archived"
