"""Translate step — translate a Page into additional store languages.

See docs/specs/F03-copy.md criterion 6, docs/03-shopify-integration.md §5.1.
- Given shop has additional published languages (from shopLocales, limited to nl/en/de)
- Merchant chooses "Vertaal" in the editor
- Mosaiq runs the copy prompt again in that language (same angle, same section order, written natively)
- Stores in Page.sections[<lang>]
- Runs compliance check for that language
- Publishes a separate metaobject entry with handle suffix -<lang> (03 §5.1)
- Does NOT count as a store generation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.core.shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from apps.core.models import Shop
    from apps.generator.models import Page

logger = logging.getLogger(__name__)

# Supported translation languages (limited to nl/en/de)
SUPPORTED_LOCALES = {"nl", "en", "de"}


def get_published_shop_locales(shop: Shop) -> list[str]:
    """Get published shop locales, limited to nl/en/de (F03 criterion 6)."""
    from apps.core.crypto import decrypt_token

    token = decrypt_token(shop.access_token_encrypted)
    client = ShopifyGraphQLClient(
        shop_domain=shop.domain,
        access_token=token,
        api_version="2026-07",
    )

    try:
        data = client.execute(load_query("shop_locales"), {})
        locales = data.get("shopLocales", [])
        return [loc["locale"] for loc in locales if loc.get("locale") in SUPPORTED_LOCALES and loc.get("published")]
    finally:
        client.close()


def get_translation_status(page: Page) -> dict[str, Any]:
    """Get which languages are already translated for a page.

    Returns dict with:
    - available: list of shop locales not yet translated
    - translated: list of languages already in Page.sections
    """
    locale = page.content_locale
    sections = page.sections or {}

    translated = [lang for lang in sections if lang != locale]

    # Get available shop locales
    try:
        shop_locales = get_published_shop_locales(page.shop)
    except Exception:
        shop_locales = list(SUPPORTED_LOCALES)

    available = [
        lang for lang in shop_locales if lang in SUPPORTED_LOCALES and lang not in translated and lang != locale
    ]

    return {
        "translated": translated,
        "available": available,
        "source_locale": locale,
    }


def translate_page(page: Page, target_locale: str) -> tuple[bool, str, dict[str, Any] | None]:
    """Translate a Page into a target language (F03 criterion 6).

    1. Re-run copy prompt in target language (same angle, same section order, written natively)
    2. Store in Page.sections[<lang>]
    3. Run compliance check for that language
    4. Publish metaobject entry with handle suffix -<lang> (03 §5.1)
    5. Does NOT count as a store generation

    Returns (success, message, output_dict).
    """
    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import SectionsPayload
    from apps.compliance.claims import check_sections
    from apps.compliance.scoring import page_score
    from apps.themes.models import BrandKit

    if target_locale not in SUPPORTED_LOCALES:
        return False, f"Unsupported locale: {target_locale}", None

    if target_locale == page.content_locale:
        return False, "Target locale is the same as source locale", None

    job = page.job
    if not job:
        return False, "Page has no associated job", None

    # Load ImportResult + ResearchResult from the job
    from apps.generator.models import JobStep

    import_step = JobStep.objects.filter(job=job, name="import", status="succeeded").first()
    research_step = JobStep.objects.filter(job=job, name="research", status="succeeded").first()

    if not import_step or not research_step:
        return False, "Job missing import/research results", None

    import_result = import_step.output
    research_output = research_step.output

    chosen_angle = research_output.get("chosen_angle") or next(
        (a for a in research_output.get("angles", []) if a.get("id") == job.input.get("angle_id")),
        None,
    )
    if not chosen_angle:
        return False, "No chosen angle found", None

    # Use the SAME section order from the existing page (F03 criterion 6)
    source_locale = page.content_locale
    source_sections = page.sections.get(source_locale, {})
    existing_section_order = [s.get("type", "") for s in source_sections.get("sections", [])]

    # Get guarantee_policy
    guarantee_policy = page.shop.guarantee_policy

    # Load BrandKit tone
    tone = "friendly"
    try:
        brandkit = BrandKit.objects.get(shop=page.shop)
        tone = brandkit.tone
    except BrandKit.DoesNotExist:
        pass

    niche = research_output.get("niche", "other")

    # Render prompt with target language
    system_prompt, user_prompt = render_prompt(
        "copy",
        {
            "import_result": import_result,
            "research_result": research_output,
            "chosen_angle": chosen_angle,
            "section_order": existing_section_order,
            "page_type": page.page_type or "pdp",
            "tone": tone,
            "niche": niche,
            "content_locale": target_locale,
            "guarantee_policy": guarantee_policy,
        },
    )

    # Call AI (no step — translation does not count as generation)
    payload = call_ai(
        shop=page.shop,
        purpose="copy",
        model_key="claude",
        system=system_prompt,
        user=user_prompt,
        schema=SectionsPayload,
        tool_name="sections_payload",
    )

    # Convert to dict
    sections_list = []
    for section in payload.sections:
        if hasattr(section, "model_dump"):
            sections_list.append(section.model_dump())
        elif isinstance(section, dict):
            sections_list.append(section)

    seo_title = payload.seo_title if hasattr(payload, "seo_title") else ""
    seo_description = payload.seo_description if hasattr(payload, "seo_description") else ""

    # Run compliance check for target language
    findings = check_sections(sections_list, target_locale)
    score = page_score(findings)

    # Store in Page.sections[<lang>]
    if page.sections is None:
        page.sections = {}
    page.sections[target_locale] = {
        "sections": sections_list,
        "seo_title": seo_title,
        "seo_description": seo_description,
    }
    page.save(update_fields=["sections"])

    # Generate metaobject handle suffix (03 §5.1)
    short_id = str(page.id)[:8]
    metaobject_handle = f"mq-{page.page_type}-{short_id}-{target_locale}"

    output = {
        "page_id": str(page.id),
        "target_locale": target_locale,
        "metaobject_handle": metaobject_handle,
        "compliance_score": score,
        "sections_count": len(sections_list),
    }

    logger.info(
        "Translated page %s to %s (%d sections, score=%d)",
        page.id,
        target_locale,
        len(sections_list),
        score,
    )
    return True, "Translated", output
