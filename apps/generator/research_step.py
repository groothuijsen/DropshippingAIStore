"""Research step — runs AI research on the import result.

See docs/05-ai-pipeline.md §4.2, docs/specs/F02-research.md.
Output: ResearchResult with exactly 3 angles, 2-3 personas, 4-8 FAQs.
If angle_id empty → job needs_input; merchant chooses angle.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import GenerationJob, JobStatus, JobStep

logger = logging.getLogger(__name__)

NUM_ANGLES = 3
MIN_PERSONAS = 2
MAX_PERSONAS = 3
MIN_FAQS = 4
MAX_FAQS = 8


def run_research(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Run the research step for a job.

    1. Load ImportResult from the import step checkpoint
    2. Load BrandKit tone + niche_hint
    3. Call AI with prompts/research.md
    4. Validate ResearchResult (exactly 3 angles)
    5. Store output, set needs_input if no angle_id
    """
    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import ResearchResult

    # Load ImportResult from import step checkpoint
    import_step = JobStep.objects.filter(job=job, name="import", status="succeeded").first()
    if not import_step or not import_step.output:
        logger.error("No import result for job %s", job.id)
        return None

    import_result = import_step.output

    # Load BrandKit tone
    tone = "friendly"
    from apps.themes.models import BrandKit

    try:
        brandkit = BrandKit.objects.get(shop=job.shop)
        tone = brandkit.tone
    except BrandKit.DoesNotExist:
        pass

    # Niche hint from job input
    niche_hint = job.input.get("niche_hint", "")

    # Render prompt
    prompt = render_prompt(
        "research",
        {
            "import_result": import_result,
            "niche_hint": niche_hint,
            "tone": tone,
            "content_locale": job.content_locale,
        },
    )

    # Call AI with tool use
    research = call_ai(
        shop=job.shop,
        purpose="research",
        model_key="claude",
        system=prompt,
        user="Generate research for this product.",
        schema=ResearchResult,
        tool_name="research_result",
        step=step,
    )

    # Validate angle count
    if len(research.angles) != NUM_ANGLES:
        logger.error("ResearchResult must have exactly %d angles, got %d", NUM_ANGLES, len(research.angles))
        return None

    # Store output
    output = research.model_dump(mode="json")

    # Set needs_input if no angle chosen yet
    angle_id = job.input.get("angle_id")
    if not angle_id:
        job.status = JobStatus.NEEDS_INPUT
        job.current_step = "research"
        job.save(update_fields=["status", "current_step"])

    return output


def select_angle(job: GenerationJob, angle_id: str) -> bool:
    """Merchant selects an angle. Stores it and resumes the job.

    Returns True if angle was valid.
    """
    from .tasks import execute_job

    # Validate angle exists in research output
    research_step = JobStep.objects.filter(job=job, name="research", status="succeeded").first()
    if not research_step or not research_step.output:
        return False

    angles = research_step.output.get("angles", [])
    valid_ids = [a.get("id") for a in angles]
    if angle_id not in valid_ids:
        return False

    # Store angle choice
    job.input["angle_id"] = angle_id
    job.save(update_fields=["input"])

    # Set angle in research output for downstream steps
    for angle in angles:
        if angle.get("id") == angle_id:
            research_step.output["chosen_angle"] = angle
            research_step.save(update_fields=["output"])
            break

    # Resume job
    job.status = JobStatus.QUEUED
    job.current_step = None
    job.save(update_fields=["status", "current_step"])

    execute_job(str(job.id))
    return True


def get_angle_cards(job: GenerationJob) -> list[dict[str, Any]]:
    """Get angle cards for the merchant UI (09 §4)."""
    research_step = JobStep.objects.filter(job=job, name="research", status="succeeded").first()
    if not research_step or not research_step.output:
        return []

    angles = research_step.output.get("angles", [])
    cards = []
    for angle in angles:
        cards.append(
            {
                "id": angle.get("id", ""),
                "title": angle.get("title", ""),
                "hook": angle.get("hook", ""),
                "persona": angle.get("persona", ""),
            }
        )
    return cards
