"""Tests for T-050: layout step + publish step + store jobs."""

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.errors import GpsrIncomplete
from apps.generator.layout_step import (
    METAOBJECT_FIELD_MAP,
    PAGE_TYPES_NEEDING_SHOPIFY_PAGE,
    build_metaobject_fields,
    get_template_suffix,
)
from apps.generator.models import (
    GenerationJob,
    JobKind,
    JobStatus,
    JobStep,
    Page,
    StepStatus,
)
from apps.generator.publish_step import run_publish
from apps.generator.store_jobs import (
    check_store_job_complete,
    create_store_child_jobs,
    get_store_job_progress,
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
def store_job(db, shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.STORE,
        content_locale="nl",
        input={
            "product_gid": "gid://shopify/Product/123",
            "niche_hint": "wellness",
            "angle_id": "a1",
        },
        status=JobStatus.RUNNING,
    )


@pytest.fixture
def page_job(db, shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type="pdp",
        content_locale="nl",
        input={"product_gid": "gid://shopify/Product/123", "angle_id": "a1"},
        status=JobStatus.RUNNING,
    )


# ── Layout step tests ─────────────────────────────────────────────────────


class TestLayoutStep:
    def test_build_metaobject_fields_hero(self):
        page = Page(
            shop_id=1,
            page_type="pdp",
            content_locale="nl",
            sections={
                "nl": {
                    "sections": [
                        {"type": "hero", "headline": "Test", "subheadline": "Sub", "cta_label": "Koop"},
                    ],
                    "seo_title": "SEO Title",
                    "seo_description": "SEO Desc",
                }
            },
            images={"hero": "gid://shopify/MediaImage/1"},
        )
        fields = build_metaobject_fields(page)
        assert "hero_headline" in fields
        assert json.loads(fields["hero_headline"]) == "Test"
        assert "seo_title" in fields
        assert json.loads(fields["seo_title"]) == "SEO Title"

    def test_build_metaobject_fields_cta(self):
        page = Page(
            shop_id=1,
            page_type="pdp",
            content_locale="nl",
            sections={
                "nl": {
                    "sections": [
                        {"type": "cta", "headline": "Buy now", "subheadline": "Great deal", "button_label": "Go"},
                    ]
                }
            },
        )
        fields = build_metaobject_fields(page)
        assert "cta_headline" in fields
        assert json.loads(fields["cta_headline"]) == "Buy now"

    def test_get_template_suffix_not_ready(self):
        shop = MagicMock(mosaiq_templates_ready=False)
        assert get_template_suffix(shop) is None

    def test_get_template_suffix_ready(self):
        shop = MagicMock(mosaiq_templates_ready=True)
        assert get_template_suffix(shop) == "mosaiq"

    def test_field_map_covers_all_section_types(self):
        """All section types from copy_step should be in the field map."""
        from apps.generator.copy_step import SECTION_ORDER

        for _page_type, sections in SECTION_ORDER.items():
            for section_type in sections:
                assert section_type in METAOBJECT_FIELD_MAP, f"{section_type} missing from METAOBJECT_FIELD_MAP"


# ── Publish step tests ────────────────────────────────────────────────────


class TestPublishStep:
    @patch("apps.generator.publish_step._get_client")
    @patch("apps.generator.publish_step.check_gpsr_for_publish")
    def test_publish_gpsr_incomplete(self, mock_gpsr, mock_client, shop, page_job):
        """GPSR incomplete → GPSR_INCOMPLETE, no write actions."""
        mock_gpsr.return_value = (False, "GPSR incomplete: missing manufacturer_name")

        Page.objects.create(
            shop=shop,
            job=page_job,
            page_type="pdp",
            title="Test",
            content_locale="nl",
        )

        with pytest.raises(GpsrIncomplete):
            run_publish(page_job, JobStep(job=page_job, name="publish"))

    @patch("apps.generator.publish_step._get_client")
    @patch("apps.generator.publish_step.check_gpsr_for_publish")
    def test_publish_no_layout_output(self, mock_gpsr, mock_client, shop, page_job):
        """No layout step output → None."""
        mock_gpsr.return_value = (True, "")
        Page.objects.create(shop=shop, job=page_job, page_type="pdp", title="T", content_locale="nl")

        result = run_publish(page_job, JobStep(job=page_job, name="publish"))
        assert result is None

    @patch("apps.generator.publish_step._get_client")
    @patch("apps.generator.publish_step.check_gpsr_for_publish")
    @patch("apps.generator.publish_step._upsert_metaobject")
    @patch("apps.generator.publish_step._create_or_update_page")
    def test_publish_success(
        self,
        mock_page,
        mock_upsert,
        mock_gpsr,
        mock_client,
        shop,
        page_job,
    ):
        """Successful publish: metaobject upsert + version increment."""
        mock_gpsr.return_value = (True, "")
        mock_upsert.return_value = "gid://shopify/Metaobject/1"
        mock_page.return_value = None  # pdp doesn't need a Shopify page
        mock_client.return_value.close = MagicMock()

        page = Page.objects.create(
            shop=shop,
            job=page_job,
            page_type="pdp",
            title="Test",
            content_locale="nl",
        )

        JobStep.objects.create(
            job=page_job,
            name="layout",
            status=StepStatus.SUCCEEDED,
            output={"metaobject_fields": {"hero_headline": '"Test"'}, "template_suffix": None},
        )

        result = run_publish(page_job, JobStep(job=page_job, name="publish"))
        assert result is not None
        assert result["metaobject_gid"] == "gid://shopify/Metaobject/1"

        page.refresh_from_db()
        assert page.version == 1
        assert page.metaobject_gids["nl"] == "gid://shopify/Metaobject/1"

    @patch("apps.generator.publish_step._get_client")
    @patch("apps.generator.publish_step.check_gpsr_for_publish")
    @patch("apps.generator.publish_step._upsert_metaobject")
    @patch("apps.generator.publish_step._create_or_update_page")
    def test_publish_landing_page_creates_shopify_page(
        self,
        mock_page,
        mock_upsert,
        mock_gpsr,
        mock_client,
        shop,
    ):
        """landing page type → creates a Shopify page."""
        mock_gpsr.return_value = (True, "")
        mock_upsert.return_value = "gid://shopify/Metaobject/1"
        mock_page.return_value = "gid://shopify/Page/1"
        mock_client.return_value.close = MagicMock()

        job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.PAGE,
            page_type="landing",
            content_locale="nl",
            input={},
            status=JobStatus.RUNNING,
        )
        Page.objects.create(
            shop=shop,
            job=job,
            page_type="landing",
            title="Landing",
            content_locale="nl",
        )
        JobStep.objects.create(
            job=job,
            name="layout",
            status=StepStatus.SUCCEEDED,
            output={"metaobject_fields": {}, "template_suffix": "mosaiq"},
        )

        result = run_publish(job, JobStep(job=job, name="publish"))
        assert result is not None
        mock_page.assert_called_once()

    def test_page_types_needing_shopify_page(self):
        assert "landing" in PAGE_TYPES_NEEDING_SHOPIFY_PAGE
        assert "pdp" not in PAGE_TYPES_NEEDING_SHOPIFY_PAGE


# ── Store jobs tests ──────────────────────────────────────────────────────


class TestStoreJobs:
    def _make_checkpoints(self, job):
        JobStep.objects.create(
            job=job,
            name="import",
            status=StepStatus.SUCCEEDED,
            output={"title": "Test", "price": "29.99"},
        )
        JobStep.objects.create(
            job=job,
            name="research",
            status=StepStatus.SUCCEEDED,
            output={"niche": "wellness", "angles": [{"id": "a1"}], "chosen_angle": {"id": "a1"}},
        )

    def test_create_child_jobs(self, store_job):
        self._make_checkpoints(store_job)
        children = create_store_child_jobs(store_job, "nl")
        assert len(children) == 3
        page_types = {c.page_type for c in children}
        assert page_types == {"home", "pdp", "about"}

    def test_child_jobs_have_checkpoints(self, store_job):
        self._make_checkpoints(store_job)
        children = create_store_child_jobs(store_job, "nl")
        for child in children:
            import_step = child.steps.filter(name="import").first()
            research_step = child.steps.filter(name="research").first()
            assert import_step is not None
            assert research_step is not None
            assert import_step.status == StepStatus.SUCCEEDED
            assert research_step.status == StepStatus.SUCCEEDED

    def test_child_jobs_have_parent(self, store_job):
        self._make_checkpoints(store_job)
        children = create_store_child_jobs(store_job, "nl")
        for child in children:
            assert child.parent == store_job

    def test_create_child_jobs_no_checkpoints(self, store_job):
        """No checkpoints → no children."""
        children = create_store_child_jobs(store_job, "nl")
        assert children == []

    def test_store_job_complete_all_succeeded(self, store_job):
        self._make_checkpoints(store_job)
        children = create_store_child_jobs(store_job, "nl")
        for child in children:
            child.status = JobStatus.SUCCEEDED
            child.save(update_fields=["status"])
        assert check_store_job_complete(store_job) is True

    def test_store_job_not_complete_one_pending(self, store_job):
        self._make_checkpoints(store_job)
        children = create_store_child_jobs(store_job, "nl")
        children[0].status = JobStatus.SUCCEEDED
        children[0].save(update_fields=["status"])
        assert check_store_job_complete(store_job) is False

    def test_store_job_progress(self, store_job):
        self._make_checkpoints(store_job)
        children = create_store_child_jobs(store_job, "nl")
        children[0].status = JobStatus.SUCCEEDED
        children[0].save(update_fields=["status"])

        progress = get_store_job_progress(store_job)
        assert progress["total"] == 3
        assert progress["succeeded"] == 1
        assert progress["complete"] is False
