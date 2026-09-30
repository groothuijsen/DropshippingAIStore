"""Celery tasks for generator — orchestration with checkpoints.

See docs/05-ai-pipeline.md §1.
Orchestration: run_job(job_id) builds a Celery chain of steps not yet succeeded.
Limits integration: reserve at job start, consume on success, release on failure (08 §1).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from celery import shared_task
from django.utils import timezone

from .errors import AiBudgetExceeded, check_job_budget
from .models import GenerationJob, JobStatus, JobStep, StepStatus

logger = logging.getLogger(__name__)

# Step order for a page job (05 §1)
PAGE_STEP_ORDER: list[str] = ["import", "research", "copy", "images", "compliance_check", "layout", "publish"]

# Step order for a store job (05 §1): only import and research
STORE_STEP_ORDER: list[str] = ["import", "research"]


def _reserve_usage(job: GenerationJob) -> bool:
    """Reserve store_generations for this job. Returns False if limit reached."""
    from apps.billing.limits import reserve

    result = reserve(job.shop, "store_generations", 1)
    if not result.allowed:
        logger.info("Plan limit reached for shop %s: %s", job.shop_id, result.message)
        return False
    return True


def _consume_usage(job: GenerationJob) -> None:
    """Convert reservation to consumption on job success."""
    from apps.billing.limits import consume

    consume(job.shop, "store_generations", 1)


def _release_usage(job: GenerationJob) -> None:
    """Release reservation on job failure."""
    from apps.billing.limits import release

    release(job.shop, "store_generations", 1)


def get_pending_steps(job: GenerationJob) -> list[JobStep]:
    """Get the steps that need to run (not yet succeeded, not skipped).

    Steps with status 'succeeded' are skipped on restart (checkpoint).
    """
    step_order = STORE_STEP_ORDER if job.kind == "store" else PAGE_STEP_ORDER

    # Get or create step rows
    steps: dict[str, JobStep] = {}
    for step_name in step_order:
        step, _ = JobStep.objects.get_or_create(
            job=job,
            name=step_name,
            defaults={"status": StepStatus.PENDING},
        )
        steps[step_name] = step

    # Return only steps that need to run
    return [steps[name] for name in step_order if steps[name].status not in (StepStatus.SUCCEEDED, StepStatus.SKIPPED)]


def update_job_from_steps(job: GenerationJob) -> None:
    """Recalculate job status from step statuses."""
    steps = JobStep.objects.filter(job=job)

    if any(s.status == StepStatus.RUNNING for s in steps):
        job.status = JobStatus.RUNNING
    elif any(s.status == StepStatus.FAILED for s in steps):
        job.status = JobStatus.FAILED
    elif all(s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for s in steps):
        job.status = JobStatus.SUCCEEDED
        job.finished_at = timezone.now()
    else:
        # Some pending, none failed/running → still queued or needs_input
        if job.status not in (JobStatus.NEEDS_INPUT, JobStatus.CANCELLED):
            job.status = JobStatus.QUEUED

    # Update current_step to the first non-succeeded step
    next_step = steps.filter(status__in=[StepStatus.PENDING, StepStatus.RUNNING]).order_by("created_at").first()
    job.current_step = next_step.name if next_step else None
    job.save(update_fields=["status", "current_step", "finished_at"])


def accumulate_job_cost(job: GenerationJob) -> None:
    """Update job.ai_cost_usd from the sum of its steps."""
    total = JobStep.objects.filter(job=job).aggregate(total=models_sum("ai_cost_usd"))["total"] or Decimal("0")
    job.ai_cost_usd = total
    job.save(update_fields=["ai_cost_usd"])


def models_sum(field: str) -> Any:
    """Return an aggregate expression for summing a field."""
    from django.db.models import Sum

    return Sum(field)


@shared_task(bind=True, acks_late=True, max_retries=3)
def run_job(self, job_id: str) -> dict[str, Any]:
    """Celery task wrapper for execute_job."""
    return execute_job(job_id)


def execute_job(job_id: str) -> dict[str, Any]:
    """Run a generation job through its pending steps.

    Builds a chain of steps that are not yet succeeded.
    Each step stores output as a checkpoint in JobStep.output.
    Limits: reserve at start, consume on success, release on failure (08 §1).
    """
    from django.core.exceptions import ObjectDoesNotExist

    try:
        job = GenerationJob.objects.get(id=job_id)
    except (ObjectDoesNotExist, ValueError):
        logger.error("GenerationJob %s not found", job_id)
        return {"error": "job_not_found"}

    if job.status in (JobStatus.SUCCEEDED, JobStatus.CANCELLED):
        logger.info("Job %s already %s — skipping", job_id, job.status)
        return {"status": job.status}

    # Check budget
    try:
        check_job_budget(job.ai_cost_usd)
    except AiBudgetExceeded as exc:
        job.status = JobStatus.FAILED
        job.error_code = exc.code
        job.error_message = exc.merchant_message
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_code", "error_message", "finished_at"])
        return {"error": exc.code}

    # Get pending steps
    pending = get_pending_steps(job)
    if not pending:
        logger.info("Job %s has no pending steps", job_id)
        update_job_from_steps(job)
        return {"status": job.status}

    # Reserve usage for this job (first time only — not on resume)
    if not job.started_at and not _reserve_usage(job):
        job.status = JobStatus.FAILED
        job.error_code = "PLAN_LIMIT_REACHED"
        job.error_message = "Plan limit reached. Please upgrade your plan."
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_code", "error_message", "finished_at"])
        return {"error": "PLAN_LIMIT_REACHED"}

    # Mark job as running
    job.status = JobStatus.RUNNING
    if not job.started_at:
        job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])

    # Execute steps sequentially (each step is a Celery task in production)
    for step in pending:
        # Check budget before each step
        try:
            check_job_budget(job.ai_cost_usd)
        except AiBudgetExceeded as exc:
            step.status = StepStatus.FAILED
            step.finished_at = timezone.now()
            step.save(update_fields=["status", "finished_at"])
            job.status = JobStatus.FAILED
            job.error_code = exc.code
            job.error_message = exc.merchant_message
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_code", "error_message", "finished_at"])
            _release_usage(job)
            return {"error": exc.code}

        # Mark step as running
        step.status = StepStatus.RUNNING
        step.attempt += 1
        step.started_at = timezone.now()
        step.save(update_fields=["status", "attempt", "started_at"])

        # Execute the step (dispatch to the appropriate handler)
        try:
            result = _execute_step(job, step)
            if result is not None:
                step.output = result
            step.status = StepStatus.SUCCEEDED
            step.finished_at = timezone.now()
            step.save(update_fields=["status", "output", "finished_at"])
            logger.info("Step %s succeeded for job %s", step.name, job_id)
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.finished_at = timezone.now()
            step.save(update_fields=["status", "finished_at"])
            job.status = JobStatus.FAILED
            job.error_code = getattr(exc, "code", "UNKNOWN_ERROR")
            job.error_message = str(exc)
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_code", "error_message", "finished_at"])
            _release_usage(job)
            logger.error("Step %s failed for job %s: %s", step.name, job_id, exc)
            return {"error": job.error_code}

        # Update job status after each step
        update_job_from_steps(job)

        # Check if job needs input (e.g., research step waiting for angle choice)
        if job.status == JobStatus.NEEDS_INPUT:
            return {"status": "needs_input", "current_step": job.current_step}

    # All steps completed
    update_job_from_steps(job)
    accumulate_job_cost(job)

    # Consume usage on success
    if job.status == JobStatus.SUCCEEDED:
        _consume_usage(job)

    return {"status": job.status, "ai_cost_usd": str(job.ai_cost_usd)}


def _execute_step(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Execute a single step by dispatching to its implementation.

    Each step type calls its own run_* function from the step modules.
    """
    from .copy_step import run_copy
    from .images_step import run_images
    from .import_step import run_import_step
    from .layout_step import run_layout
    from .publish_step import run_publish
    from .research_step import run_research

    dispatch = {
        "import": lambda: run_import_step(job),
        "research": lambda: run_research(job, step),
        "copy": lambda: run_copy(job, step),
        "images": lambda: run_images(job, step),
        "compliance_check": lambda: _run_compliance_check(job, step),
        "layout": lambda: run_layout(job, step),
        "publish": lambda: run_publish(job, step),
    }

    handler = dispatch.get(step.name)
    if handler is None:
        logger.warning("Unknown step type: %s", step.name)
        return None

    logger.info("Executing step %s for job %s", step.name, job.id)
    return handler()


def _run_compliance_check(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Run compliance check on copy output."""
    from apps.compliance.claims import check_sections

    copy_step = job.steps.filter(name="copy").first()
    if not copy_step or not copy_step.output:
        logger.warning("No copy output for compliance check, job %s", job.id)
        return None

    sections_data = copy_step.output.get("sections", {})
    sections = sections_data.get("sections", [])
    locale = sections_data.get("locale", "nl")

    findings = check_sections(sections, locale)

    block_count = sum(1 for f in findings if f.severity == "block")
    warn_count = sum(1 for f in findings if f.severity == "warn")

    output = {
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "field_path": f.field_path,
                "text": f.text,
            }
            for f in findings
        ],
        "block_count": block_count,
        "warn_count": warn_count,
        "score": max(0, 100 - block_count * 25 - warn_count * 5),
    }

    # Store findings on the Page if it exists
    page = job.pages.first()
    if page:
        page.compliance_findings = output["findings"]
        page.compliance_score = output["score"]
        page.save(update_fields=["compliance_findings", "compliance_score"])

    return output
