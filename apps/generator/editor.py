"""Page editor — section editing, recheck, rewrite.

See docs/specs/F07-pages.md criteria 2-3.
- Editor shows sections with editable fields + schema length limits
- Saving reruns the deterministic claim check + updates the score
- "Rewrite this sentence" replaces only the field, respects guardrails,
  does not count as a generation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.compliance.claims import check_claims
from apps.compliance.scoring import page_score

if TYPE_CHECKING:
    from apps.generator.models import Page

logger = logging.getLogger(__name__)

# Section field length limits (mirror 05 schema limits)
FIELD_LIMITS: dict[str, int] = {
    "headline": 120,
    "subheadline": 200,
    "cta_label": 50,
    "button_label": 50,
    "title": 120,
    "text": 500,
    "seo_title": 60,
    "seo_description": 155,
}


def validate_field_length(field_key: str, value: str) -> tuple[bool, str]:
    """Validate a field value against its length limit."""
    limit = FIELD_LIMITS.get(field_key)
    if limit and len(value) > limit:
        return False, f"Field '{field_key}' exceeds maximum length {limit} (got {len(value)})"
    return True, ""


def get_sections_for_edit(page: Page) -> list[dict[str, Any]]:
    """Get sections with field limits for the editor UI."""
    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])

    result = []
    for idx, section in enumerate(sections):
        editable_fields = {}
        for key, value in section.items():
            if key == "type":
                continue
            if isinstance(value, str):
                editable_fields[key] = {
                    "value": value,
                    "limit": FIELD_LIMITS.get(key),
                }
        result.append(
            {
                "index": idx,
                "type": section.get("type", ""),
                "fields": editable_fields,
            }
        )

    return result


def update_section_field(
    page: Page,
    section_index: int,
    field_key: str,
    value: str,
) -> tuple[bool, str]:
    """Update a single field in a section.

    1. Validate length
    2. Update Page.sections
    3. Rerun deterministic claim check
    4. Update compliance_score

    Returns (success, message).
    """
    # Validate length
    valid, msg = validate_field_length(field_key, value)
    if not valid:
        return False, msg

    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])

    if section_index < 0 or section_index >= len(sections):
        return False, f"Section index {section_index} out of range"

    # Update the field
    sections[section_index][field_key] = value
    page.sections[locale] = sections_data
    page.save(update_fields=["sections"])

    # Rerun deterministic claim check on the updated section
    _recheck_and_update_score(page)

    return True, "Field updated"


def _recheck_and_update_score(page: Page) -> None:
    """Rerun deterministic claim check + update compliance_score."""
    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])

    # Run deterministic claim check
    all_findings = []
    for idx, section in enumerate(sections):
        for key, value in section.items():
            if key == "type" or not isinstance(value, str):
                continue
            findings = check_claims(
                value,
                locale,
                idx,
                f"{section.get('type', '')}.{key}",
            )
            all_findings.extend(findings)

    # Calculate scores
    p_score = page_score(all_findings)

    page.compliance_score = p_score
    page.save(update_fields=["compliance_score"])


def recheck_page(page: Page) -> None:
    """Reset compliance_check, layout, publish steps for recheck.

    Used after merchant edits text in the editor (05 §1).
    """
    from apps.generator.models import JobStep, StepStatus

    if not page.job_id:
        return

    # Reset compliance_check, layout, publish to pending
    JobStep.objects.filter(
        job_id=page.job_id,
        name__in=["compliance_check", "layout", "publish"],
    ).exclude(status=StepStatus.PENDING).update(status=StepStatus.PENDING)

    logger.info("Recheck requested for page %s (job %s)", page.id, page.job_id)


def rewrite_field(
    page: Page,
    section_index: int,
    field_key: str,
) -> tuple[bool, str, str]:
    """Rewrite a single field via AI.

    Replaces only the field concerned, respects guardrails,
    does not count as a generation (F07 criterion 3).

    Returns (success, new_value, message).
    """
    from apps.ai.anthropic_client import call_ai
    from apps.ai.schemas import RewriteResult

    locale = page.content_locale
    sections_data = page.sections.get(locale, {})
    sections = sections_data.get("sections", [])

    if section_index < 0 or section_index >= len(sections):
        return False, "", f"Section index {section_index} out of range"

    section = sections[section_index]
    current_value = section.get(field_key, "")

    if not current_value:
        return False, "", f"Field '{field_key}' is empty"

    # AI rewrite — no limit consumption
    result = call_ai(
        shop=page.shop,
        purpose="rewrite",
        model_key="claude",
        system=(
            "Rewrite the following text. Keep the same meaning and tone. "
            "Do not add claims, medical statements, or fake urgency. "
            "Respect the same length limit."
        ),
        user=f"Rewrite this {field_key}: {current_value}",
        schema=RewriteResult,
        tool_name="submit_rewrite",
    )

    new_value = result.rewritten

    # Validate length
    valid, msg = validate_field_length(field_key, new_value)
    if not valid:
        return False, "", msg

    # Update the field
    section[field_key] = new_value
    page.sections[locale] = sections_data
    page.save(update_fields=["sections"])

    # Rerun claim check
    _recheck_and_update_score(page)

    return True, new_value, "Field rewritten"
