"""Copy step — generates SectionsPayload via AI based on research + angle.

See docs/05-ai-pipeline.md §4.3, docs/specs/F03-copy.md.
Section order per page type is fixed; AI fills in the content.
On success: creates Page (status draft).
"""

from __future__ import annotations

import logging
from typing import Any

from .models import GenerationJob, JobStep, Page, PageStatus

logger = logging.getLogger(__name__)

# Section order per page type (05 §4.3)
SECTION_ORDER: dict[str, list[str]] = {
    "pdp": ["hero", "benefits", "how_it_works", "specs", "comparison", "faq", "guarantee", "cta"],
    "landing": ["hero", "problem_solution", "benefits", "how_it_works", "faq", "guarantee", "cta"],
    "advertorial": ["rich_text", "rich_text", "rich_text", "cta"],
    "listicle": [
        "rich_text",
        "listicle_item",
        "listicle_item",
        "listicle_item",
        "listicle_item",
        "listicle_item",
        "cta",
    ],
    "home": ["hero", "benefits", "how_it_works", "faq", "cta"],
    "about": ["rich_text", "rich_text", "rich_text"],
}


def get_section_order(
    page_type: str,
    import_result: dict[str, Any],
    guarantee_policy: str,
    template_order: list[str] | None = None,
) -> list[str]:
    """Get the section order for a page type.

    - If template_order is provided, use it instead of the default order
      (F08 criterion 2)
    - specs only if ImportResult.specs has >= 2 keys
    - guarantee only if Shop.guarantee_policy is filled in
    """
    base_order = template_order or SECTION_ORDER.get(page_type, SECTION_ORDER["pdp"])
    result = []

    for section_type in base_order:
        if section_type == "specs":
            specs = import_result.get("specs", {})
            if isinstance(specs, dict) and len(specs) < 2:
                continue
            if isinstance(specs, list) and len(specs) < 2:
                continue
        elif section_type == "guarantee":
            if not guarantee_policy:
                continue

        result.append(section_type)

    return result


def run_copy(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Run the copy step for a job.

    1. Load ImportResult + ResearchResult + chosen angle
    2. Determine section order
    3. Render prompt with niche guardrails
    4. Call AI with SectionsPayload schema
    5. Validate language + specs rows
    6. Create Page (draft)
    """
    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import SectionsPayload
    from apps.themes.models import BrandKit

    # Load ImportResult
    import_step = JobStep.objects.filter(job=job, name="import", status="succeeded").first()
    if not import_step or not import_step.output:
        logger.error("No import result for job %s", job.id)
        return None
    import_result = import_step.output

    # Load ResearchResult + chosen angle
    research_step = JobStep.objects.filter(job=job, name="research", status="succeeded").first()
    if not research_step or not research_step.output:
        logger.error("No research result for job %s", job.id)
        return None
    research_output = research_step.output

    chosen_angle = research_output.get("chosen_angle") or next(
        (a for a in research_output.get("angles", []) if a.get("id") == job.input.get("angle_id")),
        None,
    )
    if not chosen_angle:
        logger.error("No chosen angle for job %s", job.id)
        return None

    # Get guarantee_policy from shop
    guarantee_policy = job.shop.guarantee_policy

    # Determine section order
    page_type = job.page_type or "pdp"
    section_order = get_section_order(page_type, import_result, guarantee_policy)

    # Load BrandKit tone
    tone = "friendly"
    try:
        brandkit = BrandKit.objects.get(shop=job.shop)
        tone = brandkit.tone
    except BrandKit.DoesNotExist:
        pass

    # Niche guardrails
    niche = research_output.get("niche", "other")

    # Render prompt
    system_prompt, user_prompt = render_prompt(
        "copy",
        {
            "import_result": import_result,
            "research_result": research_output,
            "chosen_angle": chosen_angle,
            "section_order": section_order,
            "page_type": page_type,
            "tone": tone,
            "niche": niche,
            "content_locale": job.content_locale,
            "guarantee_policy": guarantee_policy,
        },
    )

    # Call AI
    payload = call_ai(
        shop=job.shop,
        purpose="copy",
        model_key="claude",
        system=system_prompt,
        user=user_prompt,
        schema=SectionsPayload,
        tool_name="sections_payload",
        step=step,
    )

    # Validate language
    from .language_detection import detect_language

    hero_text = ""
    for section in payload.sections:
        if section.get("type") == "hero":
            hero_text = section.get("headline", "")
            break

    if hero_text:
        detected = detect_language(hero_text)
        if detected and detected != job.content_locale:
            logger.warning("Language mismatch: expected %s, detected %s", job.content_locale, detected)

    # Validate specs rows
    specs = import_result.get("specs", {})
    spec_keys = {k.lower().strip() for k in specs} if isinstance(specs, dict) else set()
    for section in payload.sections:
        if section.get("type") == "specs":
            valid_rows = []
            for row in section.get("rows", []):
                label = row.get("label", "").lower().strip()
                if label in spec_keys or label.replace(" ", "_") in spec_keys:
                    valid_rows.append(row)
                else:
                    logger.warning("Removed specs row with unmatched label: %s", row.get("label"))
            section["rows"] = valid_rows

    # Create Page
    output = payload.model_dump(mode="json")
    page = Page.objects.create(
        shop=job.shop,
        job=job,
        page_type=page_type,
        content_locale=job.content_locale,
        sections={job.content_locale: output},
        title=output.get("seo_title", ""),
        seo_description=output.get("seo_description", ""),
        status=PageStatus.DRAFT,
        product_gid=job.input.get("product_gid"),
    )

    # Store page_id in output for downstream steps
    output["page_id"] = str(page.id)

    return output


def delivery_guardrail(est) -> str:
    """Copy-step delivery guardrail (12 §5, F18-9).

    Returns the guardrail text naming the product's actual max_days, or
    an empty string when no estimate exists.
    """
    if est is None:
        return ""
    return (
        f"Do not promise faster delivery than {est.max_days} working days; "
        "never say 'fast shipping' if max_days > 5."
    )
