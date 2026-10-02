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
    """Convert Page.sections + images into metaobject fields.

    Returns dict of field_key -> JSON string.
    """
    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])
    images = page.images or {}

    fields: dict[str, str] = {}

    for section in sections:
        section_type = section.get("type", "")
        field_map = METAOBJECT_FIELD_MAP.get(section_type, {})

        for field_key, section_key in field_map.items():
            if field_key == "hero_image":
                # Image field: get from page.images by slot
                image_gid = images.get("hero", "")
                fields[field_key] = json.dumps(image_gid)
            elif section_key is None:
                # Whole section dict (minus "type")
                value = {k: v for k, v in section.items() if k != "type"}
                fields[field_key] = json.dumps(value)
            elif section_key in section:
                fields[field_key] = json.dumps(section[section_key])

        # Image fields per section
        if section_type == "hero" and "hero" in images:
            fields["hero_image"] = json.dumps(images["hero"])

    # SEO fields
    if sections_data.get("seo_title"):
        fields["seo_title"] = json.dumps(sections_data["seo_title"])
    if sections_data.get("seo_description"):
        fields["seo_description"] = json.dumps(sections_data["seo_description"])

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
    from .models import Page

    # Find the page for this job
    page = Page.objects.filter(job=job).first()
    if not page:
        logger.error("No page found for job %s", job.id)
        return None

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
