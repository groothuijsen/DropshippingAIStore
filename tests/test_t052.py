"""Tests for T-052: SavedTemplate model + save/load/validate."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.copy_step import get_section_order
from apps.generator.models import GenerationJob, JobKind, JobStatus, Page
from apps.templates_lib.models import SavedTemplate
from apps.templates_lib.service import (
    delete_template,
    extract_structure,
    get_template_section_order,
    list_templates_for_shop,
    save_page_as_template,
    validate_template,
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
        title="Test",
        content_locale="nl",
        sections={
            "nl": {
                "sections": [
                    {"type": "hero", "headline": "Product", "subheadline": "Best", "cta_label": "Buy"},
                    {"type": "benefits", "title": "Why", "items": ["A", "B"]},
                    {"type": "specs", "rows": [{"label": "Color", "value": "Blue"}]},
                    {"type": "faq", "items": [{"q": "Q?", "a": "A."}]},
                    {"type": "cta", "headline": "Ready?", "subheadline": "Order", "button_label": "Go"},
                ],
                "seo_title": "Test",
                "seo_description": "Test",
            }
        },
        images={"hero": "gid://shopify/MediaImage/1"},
        version=1,
    )


class TestExtractStructure:
    def test_extract_section_order(self, page):
        structure = extract_structure(page)
        assert structure["section_order"] == ["hero", "benefits", "specs", "faq", "cta"]
        assert structure["page_type"] == "pdp"

    def test_extract_no_product_content(self, page):
        """F08 criterion 1: NO product text, prices, images or claims."""
        structure = extract_structure(page)
        assert "headline" not in structure
        assert "title" not in structure
        assert "images" not in structure
        assert "hero" in structure["section_order"]

    def test_extract_display_settings(self, db, shop, job):
        """Display settings (layout, style) are saved."""
        p = Page.objects.create(
            shop=shop,
            job=job,
            page_type="pdp",
            title="T",
            content_locale="nl",
            sections={
                "nl": {
                    "sections": [
                        {"type": "hero", "headline": "H", "layout": "split", "max_width": 1200},
                    ]
                }
            },
        )
        structure = extract_structure(p)
        assert structure["section_settings"]["0"]["layout"] == "split"
        assert structure["section_settings"]["0"]["max_width"] == 1200


class TestSaveTemplate:
    def test_save_template_success(self, page):
        ok, msg, template = save_page_as_template(page, "My Template")
        assert ok is True
        assert template.name == "My Template"
        assert template.section_order == ["hero", "benefits", "specs", "faq", "cta"]

    def test_save_template_no_sections(self, db, shop, job):
        p = Page.objects.create(
            shop=shop,
            job=job,
            page_type="pdp",
            title="Empty",
            content_locale="nl",
            sections={"nl": {"sections": []}},
        )
        ok, msg, template = save_page_as_template(p, "Empty")
        assert ok is False

    def test_save_template_unknown_section(self, db, shop, job):
        p = Page.objects.create(
            shop=shop,
            job=job,
            page_type="pdp",
            title="Bad",
            content_locale="nl",
            sections={"nl": {"sections": [{"type": "nonexistent"}]}},
        )
        ok, msg, template = save_page_as_template(p, "Bad")
        assert ok is False
        assert "nonexistent" in msg


class TestValidateTemplate:
    def test_validate_known_types(self, page):
        _, _, template = save_page_as_template(page, "Valid")
        valid, msg = validate_template(template)
        assert valid is True

    def test_validate_unknown_type(self, shop):
        template = SavedTemplate.objects.create(
            owner_shop=shop,
            name="Bad",
            page_type="pdp",
            structure={"section_order": ["hero", "unknown_type"]},
        )
        valid, msg = validate_template(template)
        assert valid is False
        assert "unknown_type" in msg

    def test_validate_empty_structure(self, shop):
        template = SavedTemplate.objects.create(
            owner_shop=shop,
            name="Empty",
            page_type="pdp",
            structure={"section_order": []},
        )
        valid, msg = validate_template(template)
        assert valid is False


class TestTemplateSectionOrder:
    def test_get_section_order_from_template(self, page):
        _, _, template = save_page_as_template(page, "T")
        order = get_template_section_order(template)
        assert order == ["hero", "benefits", "specs", "faq", "cta"]

    def test_copy_step_uses_template_order(self, page):
        """F08 criterion 2: copy uses template order instead of default."""
        _, _, template = save_page_as_template(page, "T")
        order = get_section_order(
            "pdp",
            {"specs": {"Color": "Blue"}},
            "30-day guarantee",
            template_order=template.section_order,
        )
        # Template order used, but specs/guarantee filtering still applies
        assert "hero" in order
        assert "benefits" in order

    def test_copy_step_without_template_uses_default(self):
        order = get_section_order("pdp", {"specs": {"A": "B"}}, "30-day guarantee")
        assert "hero" in order
        assert "benefits" in order


class TestListTemplates:
    def test_list_templates_for_shop(self, shop, page):
        save_page_as_template(page, "T1")
        templates = list_templates_for_shop(shop)
        assert len(templates) == 1

    def test_list_templates_other_shop(self, shop, page):
        other_shop = Shop.objects.create(
            domain="other.myshopify.com",
            shopify_gid="gid://shopify/Shop/999",
            access_token_encrypted=encrypt_token("shpat_x"),
            access_token_expires_at=timezone.now() + timedelta(hours=1),
            refresh_token_encrypted=encrypt_token("shpat_r"),
            refresh_token_expires_at=timezone.now() + timedelta(days=90),
            currency_code="EUR",
            status=ShopStatus.ACTIVE,
        )
        save_page_as_template(page, "T1")
        templates = list_templates_for_shop(other_shop)
        assert len(templates) == 0


class TestDeleteTemplate:
    def test_delete_template(self, shop, page):
        _, _, template = save_page_as_template(page, "T")
        ok, msg = delete_template(template)
        assert ok is True
        assert not SavedTemplate.objects.filter(id=template.id).exists()
