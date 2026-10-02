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


# ── Store-builder wizard: name suggestions (F15-4, T-112) ─────────────────

LOCALE_NAMES = {"nl": "Dutch", "en": "English", "de": "German"}


def check_domain_status(name: str) -> str:
    """Heuristic .com availability via rdap.org (F15-4).

    404 → likely_free, 200 → taken, anything else / error → unknown.
    Low volume (8 names × ≤4 generations), spaced by the caller (Q21).
    """
    import httpx

    url = f"https://rdap.org/domain/{name.lower()}.com"
    try:
        resp = httpx.get(url, timeout=5.0, follow_redirects=True)
        if resp.status_code == 404:
            return "likely_free"
        if resp.status_code == 200:
            return "taken"
        return "unknown"
    except Exception:
        return "unknown"


def _blocklist_terms(locales: list[str]) -> str:
    """Comma-joined generic-claim terms for the chosen locales (prompt var)."""
    from apps.themes.brand_blocklist import GENERIC_CLAIM_TERMS

    return ", ".join(sorted(GENERIC_CLAIM_TERMS)[:20])


def _filter_name_ideas(ideas: list, seen: set[str]) -> list[dict[str, Any]]:
    """Validate NameIdea objects against the blocklist; dedupe; to dicts."""
    from apps.themes.brand_blocklist import is_blocked_brand

    kept: list[dict[str, Any]] = []
    for idea in ideas:
        name = idea.name.strip()
        if not name or name.lower() in seen:
            continue
        if is_blocked_brand(name):
            logger.info("Name suggestion blocked: %s", name)
            continue
        seen.add(name.lower())
        kept.append(
            {
                "name": name,
                "rationale": idea.rationale,
                "pronunciation_ok": list(idea.pronunciation_ok),
                "domain_status": "unknown",
            }
        )
    return kept


@shared_task(acks_late=True, max_retries=2)
def generate_name_suggestions(blueprint_id: str) -> None:
    """F15-4: one AI call (niche_names.md) → 8 names, blocklisted, RDAP-checked.

    Names that fail the blocklist are dropped; the call is repeated once for
    the missing count. RDAP failures yield domain_status "unknown", never an
    error. Result stored on StoreBlueprint.name_suggestions.
    """
    import time

    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import NameSuggestions
    from apps.generator.models import StoreBlueprint

    try:
        bp = StoreBlueprint.objects.get(id=blueprint_id)
    except StoreBlueprint.DoesNotExist:
        logger.warning("StoreBlueprint %s not found — names task exiting", blueprint_id)
        return

    if bp.status != "names":
        logger.info("Blueprint %s status %s — names task skipping", blueprint_id, bp.status)
        return

    locales = bp.content_locales or ["en"]
    locale_names = ", ".join(LOCALE_NAMES.get(loc, loc) for loc in locales)
    brief_json = bp.description or ""
    variables = {
        "brief_json": brief_json,
        "locale_names": locale_names,
        "exclude_names": "",
        "blocklist_terms": _blocklist_terms(locales),
    }

    def _call(count: int, exclude: str):
        variables["exclude_names"] = exclude
        system, user = render_prompt("niche_names", variables)
        return call_ai(
            shop=bp.shop,
            purpose="niche_names",
            model_key="copy",  # prompt header: Model LLM_MODEL_COPY
            system=system,
            user=f"Generate {count} brand name suggestions.",
            schema=NameSuggestions,
            tool_name="submit_names",
        )

    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    try:
        result = _call(8, "")
        kept = _filter_name_ideas(result.names, seen)
        if len(kept) < 8:
            missing = 8 - len(kept)
            retry = _call(missing, ", ".join(item["name"] for item in kept))
            kept.extend(_filter_name_ideas(retry.names, seen))
    except Exception as exc:
        logger.error("Name suggestion AI call failed for %s: %s", blueprint_id, exc)
        return

    kept = kept[:8]
    for item in kept:
        item["domain_status"] = check_domain_status(item["name"])
        time.sleep(0.5)  # RDAP spacing (Q21 guardrail)

    bp.name_suggestions = kept
    bp.save(update_fields=["name_suggestions", "updated_at"])
    logger.info("Stored %d name suggestions for blueprint %s", len(kept), blueprint_id)


# ── Store-builder wizard: brand proposal (F15-5, T-113) ──────────────────


@shared_task(acks_late=True, max_retries=2)
def generate_brand_proposal(blueprint_id: str) -> None:
    """One niche_brand call → BrandProposal, corrected per F05-3/4.

    Invalid font keys fall back to ``theme`` (inherit); a failing
    text-on-background contrast is corrected with the suggestion from
    ``validate_palette`` (never silently kept).
    """
    import json

    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import BrandProposal
    from apps.generator.models import StoreBlueprint
    from apps.themes.fonts import get_font_keys, is_valid_font
    from apps.themes.presets import STYLE_PRESETS
    from apps.themes.validation import validate_palette

    try:
        bp = StoreBlueprint.objects.get(id=blueprint_id)
    except StoreBlueprint.DoesNotExist:
        logger.warning("Brand proposal: blueprint %s not found", blueprint_id)
        return
    if bp.status != "brand" or bp.brand_proposal is not None:
        return  # not in the brand state, or already proposed

    font_lines = ", ".join(get_font_keys())
    presets_json = json.dumps(STYLE_PRESETS, ensure_ascii=False)
    system, user = render_prompt(
        "niche_brand",
        {
            "brand_name": bp.brand_name,
            "brief_json": json.dumps(
                {
                    "description": bp.description,
                    "markets": bp.markets,
                    "content_locales": bp.content_locales,
                    "audience": bp.audience,
                    "price_level": bp.price_level,
                    "import_app": bp.import_app,
                },
                ensure_ascii=False,
            ),
            "font_keys": font_lines,
            "presets_json": presets_json,
            "ui_locale_name": {"nl": "Dutch", "en": "English", "de": "German"}.get(
                (bp.content_locales or ["en"])[0], "English"
            ),
        },
    )
    try:
        proposal = call_ai(  # returns the validated model (not a tuple)
            shop=bp.shop,
            purpose="brand_proposal",
            model_key="copy",
            system=system,
            user=user or "Generate a brand proposal.",
            schema=BrandProposal,
            tool_name="submit_brand",
            temperature=0.4,  # niche_brand prompt header
        )
    except Exception as exc:
        logger.error("Brand proposal AI call failed for %s: %s", bp.id, exc)
        return

    data = proposal.model_dump()
    # F05-4: font keys must come from the bundled list; else inherit theme
    if not is_valid_font(data["font_heading"]):
        data["font_heading"] = ""
    if not is_valid_font(data["font_body"]):
        data["font_body"] = ""
    # F05-3: text on background ≥ 4.5:1 — correct with the suggestion
    palette = {k: data["palette"][k] for k in ("primary", "secondary", "accent", "background", "text")}
    validation = validate_palette(palette)
    if not validation["valid"] and "text" in validation["suggestions"]:
        palette["text"] = validation["suggestions"]["text"]
    data["palette"] = palette

    bp.brand_proposal = data
    bp.save(update_fields=["brand_proposal", "updated_at"])
    logger.info("Stored brand proposal for blueprint %s", bp.id)


# ── Store-builder wizard: product ideas (F15-6, T-114) ────────────────────


@shared_task(acks_late=True, max_retries=2)
def generate_product_ideas(blueprint_id: str) -> None:
    """One product_ideas call → ProductIdeas (5–10 ideas + avoid list)."""
    import json

    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import ProductIdeas
    from apps.generator.import_apps import import_app_name
    from apps.generator.models import StoreBlueprint

    try:
        bp = StoreBlueprint.objects.get(id=blueprint_id)
    except StoreBlueprint.DoesNotExist:
        logger.warning("Product ideas: blueprint %s not found", blueprint_id)
        return
    if bp.status != "ideas" or bp.product_ideas is not None:
        return

    app_name = import_app_name(bp.import_app)
    system, user = render_prompt(
        "product_ideas",
        {
            "brand_name": bp.brand_name,
            "import_app_name": app_name,
            "brief_json": json.dumps(
                {
                    "description": bp.description,
                    "markets": bp.markets,
                    "content_locales": bp.content_locales,
                    "audience": bp.audience,
                    "price_level": bp.price_level,
                },
                ensure_ascii=False,
            ),
            "markets": ", ".join(bp.markets or []),
            "ui_locale_name": {"nl": "Dutch", "en": "English", "de": "German"}.get(
                (bp.content_locales or ["en"])[0], "English"
            ),
        },
    )
    try:
        result = call_ai(
            shop=bp.shop,
            purpose="product_ideas",
            model_key="research",  # prompt header: LLM_MODEL_RESEARCH
            system=system,
            user=user or "Generate product ideas.",
            schema=ProductIdeas,
            tool_name="submit_product_ideas",
            temperature=0.6,  # prompt header
        )
    except Exception as exc:
        logger.error("Product ideas AI call failed for %s: %s", bp.id, exc)
        return

    bp.product_ideas = result.model_dump()
    bp.save(update_fields=["product_ideas", "updated_at"])
    logger.info("Stored product ideas for blueprint %s", bp.id)


# ── Store-builder wizard: store structure (F15-8, T-115) ──────────────────

STRUCTURE_REPAIR_NOTE = (
    "Some collection.product_gids are not part of the merchant's product "
    "selection. Use ONLY these GIDs: {gids}. Return the full structure again."
)


def _fetch_products_by_ids(shop, gids: list[str]) -> list[dict]:
    """Fetch selected products for the structure prompt (gid, title, type, tags, price)."""
    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query

    if not gids:
        return []
    token = decrypt_token(shop.access_token_encrypted)
    client = ShopifyGraphQLClient(shop.domain, token, "2026-07")
    data = client.execute(load_query("products_by_ids"), {"ids": gids})
    rows: list[dict] = []
    for node in data.get("nodes") or []:
        if not node:
            continue
        rows.append(
            {
                "gid": node.get("id", ""),
                "title": node.get("title", ""),
                "productType": node.get("productType", ""),
                "tags": node.get("tags", ""),
                "price": (node.get("priceRange") or {}).get("minVariantPrice", {}).get("amount", ""),
            }
        )
    return rows


@shared_task(acks_late=True, max_retries=2)
def generate_store_structure(blueprint_id: str) -> None:
    """One store_structure call → StoreStructure (12 §3).

    Every collection.product_gids entry must be in the merchant's
    selection (F15-8): one repair round, then a merchant-facing failure
    message in ``structure_error``.
    """
    import json

    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import StoreStructure
    from apps.generator.models import StoreBlueprint

    try:
        bp = StoreBlueprint.objects.get(id=blueprint_id)
    except StoreBlueprint.DoesNotExist:
        logger.warning("Store structure: blueprint %s not found", blueprint_id)
        return
    if bp.status != "structure" or bp.store_structure is not None:
        return  # not in the structure state, or already proposed

    selection = list(bp.selected_product_gids or [])
    if not selection:
        StoreBlueprint.objects.filter(id=bp.id).update(
            structure_error="No products selected — go back and select the products to organise."
        )
        return

    try:
        products = _fetch_products_by_ids(bp.shop, selection)
    except Exception as exc:
        logger.error("Store structure: product fetch failed for %s: %s", bp.id, exc)
        StoreBlueprint.objects.filter(id=bp.id).update(
            structure_error="Could not load your selected products. Try again."
        )
        return

    variables = {
        "brief_json": json.dumps(
            {
                "description": bp.description,
                "markets": bp.markets,
                "audience": bp.audience,
                "price_level": bp.price_level,
            },
            ensure_ascii=False,
        ),
        "brand_name": bp.brand_name or "",
        "products_json": json.dumps(products, ensure_ascii=False),
        "content_locale_name": {"nl": "Dutch", "en": "English", "de": "German"}.get(
            (bp.content_locales or ["en"])[0], "English"
        ),
    }
    system, user = render_prompt("store_structure", variables)

    selection_set = set(selection)
    repair_note = ""
    for attempt in range(2):  # one repair round (F15-8)
        prompt_user = user or "Generate the store structure."
        if repair_note:
            prompt_user = f"{prompt_user}\n\n{repair_note}"
        try:
            structure = call_ai(
                shop=bp.shop,
                purpose="store_structure",
                model_key="copy",
                system=system,
                user=prompt_user,
                schema=StoreStructure,
                tool_name="submit_structure",
                temperature=0.3,  # store_structure prompt header
            )
        except Exception as exc:
            logger.error(
                "Store structure AI call failed for %s (attempt %s): %s", bp.id, attempt + 1, exc
            )
            StoreBlueprint.objects.filter(id=bp.id).update(
                structure_error="Could not generate a store structure. Please try again."
            )
            return

        invalid = sorted(
            {
                gid
                for coll in structure.collections
                for gid in coll.product_gids
                if gid not in selection_set
            }
        )
        if not invalid:
            StoreBlueprint.objects.filter(id=bp.id).update(
                store_structure=structure.model_dump(), structure_error=""
            )
            return
        repair_note = STRUCTURE_REPAIR_NOTE.format(gids=", ".join(selection))

    StoreBlueprint.objects.filter(id=bp.id).update(
        structure_error=(
            "The generated structure references products that are not part "
            "of your product selection. Please try again."
        )
    )
