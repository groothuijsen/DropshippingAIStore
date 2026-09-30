"""Template service — save, load, validate templates.

See docs/specs/F08-templates.md.
- save_page_as_template: extract structure from Page (NO product content)
- get_template_section_order: returns section order for copy step
- validate_template: rejects unknown section types with clear message
- MVP: templates only within the same shop (shared_with_account hidden)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .models import SavedTemplate

if TYPE_CHECKING:
    from apps.generator.models import Page

logger = logging.getLogger(__name__)

# Known section types (must match copy_step.SECTION_ORDER values)
KNOWN_SECTION_TYPES = {
    "hero",
    "benefits",
    "problem_solution",
    "how_it_works",
    "specs",
    "comparison",
    "faq",
    "guarantee",
    "rich_text",
    "listicle_item",
    "cta",
}


def extract_structure(page: Page) -> dict[str, Any]:
    """Extract template structure from a Page.

    Contains: page_type, section_order, per-section type + display settings.
    NO product text, prices, images or claims (F08 criterion 1).
    """
    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])

    section_order = []
    section_settings = {}

    for idx, section in enumerate(sections):
        section_type = section.get("type", "")
        section_order.append(section_type)

        # Extract only display settings, NOT content
        # Display settings: layout, style, max_width, etc.
        settings = {}
        for key in ["layout", "style", "max_width", "show_image", "columns"]:
            if key in section:
                settings[key] = section[key]

        if settings:
            section_settings[str(idx)] = settings

    return {
        "page_type": page.page_type,
        "section_order": section_order,
        "section_settings": section_settings,
    }


def save_page_as_template(
    page: Page,
    name: str,
) -> tuple[bool, str, SavedTemplate | None]:
    """Save a Page as a SavedTemplate (F08 criterion 1).

    Returns (success, message, template).
    """
    # Validate page has sections
    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])
    if not sections:
        return False, "Page has no sections to save as template", None

    # Extract structure (NO product content)
    structure = extract_structure(page)

    # Validate all section types are known
    unknown = [t for t in structure["section_order"] if t not in KNOWN_SECTION_TYPES]
    if unknown:
        return False, f"Unknown section types: {', '.join(unknown)}", None

    # Create template
    template = SavedTemplate.objects.create(
        owner_shop=page.shop,
        name=name,
        page_type=page.page_type,
        structure=structure,
    )

    logger.info("Saved template %s from page %s", template.id, page.id)
    return True, "Template saved", template


def get_template_section_order(template: SavedTemplate) -> list[str]:
    """Get section order from a template for the copy step (F08 criterion 2)."""
    return template.section_order


def validate_template(template: SavedTemplate) -> tuple[bool, str]:
    """Validate a template has only known section types (F08 criterion 3).

    Returns (valid, message).
    """
    order = template.section_order
    if not order:
        return False, "Template has no section order"

    unknown = [t for t in order if t not in KNOWN_SECTION_TYPES]
    if unknown:
        return False, f"Unknown section types: {', '.join(unknown)}"

    return True, ""


def list_templates_for_shop(shop: Any) -> list[SavedTemplate]:
    """List templates for a shop (MVP: own shop only, F08 criterion 4)."""
    return list(SavedTemplate.objects.filter(owner_shop=shop).order_by("-created_at"))


def delete_template(template: SavedTemplate) -> tuple[bool, str]:
    """Delete a template."""
    template_id = template.id
    template.delete()
    logger.info("Deleted template %s", template_id)
    return True, "Template deleted"
