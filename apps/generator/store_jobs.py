"""Store jobs — creates child jobs for home, pdp, about.

See docs/05-ai-pipeline.md §1.
For kind=store: runs only import + research. After angle chosen:
creates 3 child jobs (parent=store job) with page_type home, pdp, about.
Each child runs its own steps starting from copy, reusing the parent's
ImportResult/ResearchResult (copied as succeeded checkpoint).
Store job is succeeded when all 3 child jobs are succeeded.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.generator.models import GenerationJob

logger = logging.getLogger(__name__)

# Child job page types for store jobs (05 §1)
STORE_CHILD_PAGE_TYPES = ["home", "pdp", "about"]


def create_store_child_jobs(
    store_job: GenerationJob,
    content_locale: str,
) -> list[GenerationJob]:
    """Create child jobs for a store job after research + angle selection.

    Args:
        store_job: The parent store job (kind=store)
        content_locale: Content locale for child jobs

    Returns:
        List of created child GenerationJob objects
    """
    from .models import GenerationJob, JobKind, JobStatus, JobStep, StepStatus

    # Load parent's import + research checkpoints
    import_step = JobStep.objects.filter(job=store_job, name="import", status=StepStatus.SUCCEEDED).first()
    research_step = JobStep.objects.filter(job=store_job, name="research", status=StepStatus.SUCCEEDED).first()

    if not import_step or not research_step:
        logger.error("Store job %s missing import/research checkpoints", store_job.id)
        return []

    # Get product_gid from store job input
    product_gid = store_job.input.get("product_gid", "")
    angle_id = store_job.input.get("angle_id", "")
    niche_hint = store_job.input.get("niche_hint", "")

    child_jobs = []

    for page_type in STORE_CHILD_PAGE_TYPES:
        # Create child job with unique idempotency key per page type
        child_job = GenerationJob.objects.create(
            shop=store_job.shop,
            kind=JobKind.PAGE,
            parent=store_job,
            page_type=page_type,
            content_locale=content_locale,
            input={
                "product_gid": product_gid,
                "niche_hint": niche_hint,
                "angle_id": angle_id,
            },
            status=JobStatus.QUEUED,
            idempotency_key=f"store-{store_job.id}-{page_type}",
        )

        # Copy parent's import checkpoint
        JobStep.objects.create(
            job=child_job,
            name="import",
            status=StepStatus.SUCCEEDED,
            output=import_step.output,
        )

        # Copy parent's research checkpoint
        JobStep.objects.create(
            job=child_job,
            name="research",
            status=StepStatus.SUCCEEDED,
            output=research_step.output,
        )

        child_jobs.append(child_job)
        logger.info(
            "Created child job %s for store job %s (page_type=%s)",
            child_job.id,
            store_job.id,
            page_type,
        )

    return child_jobs


def check_store_job_complete(store_job: GenerationJob) -> bool:
    """Check if all child jobs of a store job are succeeded.

    Returns True if store job is complete (all children succeeded).
    """
    from .models import GenerationJob, JobStatus

    children = GenerationJob.objects.filter(parent=store_job)
    if not children.exists():
        return False

    return all(child.status == JobStatus.SUCCEEDED for child in children)


def get_store_job_progress(store_job: GenerationJob) -> dict:
    """Get progress info for a store job."""
    from .models import GenerationJob, JobStatus

    children = GenerationJob.objects.filter(parent=store_job)
    total = children.count()
    succeeded = children.filter(status=JobStatus.SUCCEEDED).count()
    failed = children.filter(status=JobStatus.FAILED).count()

    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "pending": total - succeeded - failed,
        "complete": total > 0 and succeeded == total,
    }
