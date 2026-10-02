"""Layout step — converts SectionsPayload + images into metaobject fields.

See docs/05-ai-pipeline.md §4.6.
- Reads Page.sections (the edited version, not copy output)
- Converts sections + images into metaobject_fields (JSON strings)
- Sets template_suffix = "mosaiq" if Shop.mosaiq_templates_ready
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.generator.models import GenerationJob, JobStep, Page

logger = logging.getLogger(__name__)

# Metaobject field keys per section type (03 §5.1)
# Maps metaobject field key -> section dict key(s) to read from
METAOBJECT_FIELD_MAP = {
    "hero": {"hero_headline": "headline", "hero_subheadline": "subheadline", "hero_cta_label": "cta_label"},
    "benefits": {"benefits_title": "title", "benefits_items": "items"},
    "problem_solution": {"problem_solution": None},  # whole section dict
    "how_it_works": {"how_it_works_title": "title", "how_it_works_steps": "steps"},
    "specs": {"specs_rows": "rows"},
    "comparison": {"comparison": None},
    "faq": {"faq_items": "items"},
    "guarantee": {"guarantee": None},
    "rich_text": {"rich_text": None},
    "listicle_item": {"listicle_items": None},
    "cta": {"cta_headline": "headline", "cta_subheadline": "subheadline", "cta_button_label": "button_label"},
}

# Page types that need a Shopify page (not just metaobject)
PAGE_TYPES_NEEDING_SHOPIFY_PAGE = {"landing", "advertorial", "listicle", "about", "faq", "shipping", "returns"}


def build_metaobject_fields(page: Page) -> dict[str, str]:
    """Convert Page data into the $app:page_content metaobject fields.

    The definition (03 §5.1, created by installation.ensure_
    metaobject_definitions) has a fixed field set: page_type, locale,
    sections (json — the full sections payload incl. seo fields),
    image_* file references, ai_image_disclosure, version. Verified
    against the live definition on the dev store during the T-117 E2E
    ("Field definition ... does not exist" exposed the old per-section
    field map, which never matched the real definition).
    """
    locale = page.content_locale
    sections_data = page.sections.get(locale, {}) if isinstance(page.sections, dict) else {}
    sections = sections_data.get("sections", []) if isinstance(sections_data, dict) else []
    images = page.images or {}

    payload = dict(sections_data) if isinstance(sections_data, dict) else {}
    payload["sections"] = sections

    fields: dict[str, str] = {
        "page_type": json.dumps(page.page_type),
        "locale": json.dumps(locale),
        "sections": json.dumps(payload, ensure_ascii=False),
        "version": json.dumps(page.version or 1),
    }

    hero_gid = images.get("hero", "")
    if hero_gid:
        fields["image_hero"] = json.dumps(hero_gid)
    if page.ai_image_disclosure:
        fields["ai_image_disclosure"] = json.dumps(bool(page.ai_image_disclosure))

    return fields


def get_template_suffix(shop: Any) -> str | None:
    """Get template_suffix based on Shop.mosaiq_templates_ready."""
    if getattr(shop, "mosaiq_templates_ready", False):
        return "mosaiq"
    return None


def run_layout(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Run the layout step for a job.

    1. Load Page
    2. Build metaobject fields from sections + images
    3. Determine template_suffix
    4. Store in step output
    """
    # Find the page for this job
    from apps.generator.errors import PageNotFound

    from .models import Page

    page = Page.objects.filter(job=job).first()
    if not page:
        logger.error("No page found for job %s", job.id)
        raise PageNotFound()

    # Build metaobject fields
    fields = build_metaobject_fields(page)

    # Determine template suffix
    template_suffix = get_template_suffix(job.shop)

    output = {
        "page_id": str(page.id),
        "metaobject_fields": fields,
        "template_suffix": template_suffix,
        "content_locale": page.content_locale,
    }

    return output
