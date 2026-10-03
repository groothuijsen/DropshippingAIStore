"""Start with product — standalone PDP generation for existing products (F20).

The dashboard card "Start with product" lands here: pick one of the
shop's existing products, the full PDP pipeline (import → research →
copy → images → compliance_check → layout → publish) runs as one job.
No StoreBlueprint / niche wizard required — the merchant already has
the product.

Reuse rules: an in-flight PDP job for the same product redirects to
its status page instead of creating a duplicate.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

PDP_STEPS = ["import", "research", "copy", "images", "compliance_check", "layout", "publish"]
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


def _get_shop(request: HttpRequest):
    from apps.core.models import Shop

    shop_domain = getattr(request, "shop_domain", None)
    return Shop.objects.filter(domain=shop_domain).first() if shop_domain else None


def _unauthorized() -> HttpResponse:
    return HttpResponseForbidden("Unauthorized")


def _fetch_products(shop) -> list[dict]:
    """Shop products via GraphQL (same query as the import-waiting screen)."""
    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query

    try:
        token = decrypt_token(shop.access_token_encrypted)
        client = ShopifyGraphQLClient(shop.domain, token, _api_version())
        data = client.execute(load_query("products_list"), {"first": 50})
        return (data.get("products") or {}).get("nodes") or []
    except Exception as exc:  # the picker must never 500
        logger.warning("products query failed for %s: %s", shop.domain, exc)
        return []


def _api_version() -> str:
    return getattr(settings, "SHOPIFY_API_VERSION", "2026-07")


def create_pdp_job(shop, product_gid: str, locale: str, niche_hint: str = ""):
    """Create (or reuse) the PDP job for a product. Shared with the E2E demo script."""
    from apps.generator.models import GenerationJob, JobKind, JobStatus, PageType
    from apps.themes.models import BrandKit

    # Reuse an in-flight job for the same product
    for existing in GenerationJob.objects.filter(
        kind=JobKind.PAGE, page_type=PageType.PDP, shop=shop, status__in=["queued", "running", "needs_input"]
    ):
        if (existing.input or {}).get("product_gid") == product_gid:
            return existing, False

    import contextlib

    style_preset = "clean"
    with contextlib.suppress(Exception):  # BrandKit optional (research/copy degrade to defaults)
        style_preset = BrandKit.objects.get(shop=shop).style_preset or "clean"

    import uuid as _uuid

    product_key = str(product_gid).rsplit("/", 1)[-1]
    job = GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type=PageType.PDP,
        content_locale=locale,
        status=JobStatus.QUEUED,
        idempotency_key=f"pdp-{product_key}-{_uuid.uuid4().hex[:8]}",
        input={
            "product_gid": product_gid,
            "content_locale": locale,
            "niche_hint": niche_hint,
            "style_preset": style_preset,
        },
    )
    from apps.generator.models import JobStep

    for name in PDP_STEPS:
        JobStep.objects.get_or_create(job=job, name=name)
    return job, True


@require_http_methods(["GET", "POST"])
def product_start_view(request: HttpRequest) -> HttpResponse:
    """Product picker → create PDP job → redirect to the job status page."""
    shop = _get_shop(request)
    if shop is None:
        return _unauthorized()

    if request.method == "POST":
        product_gid = request.POST.get("product_gid", "").strip()
        if not product_gid.startswith("gid://shopify/Product/"):
            messages.error(request, "Select a product first.")
            return redirect("/app/start/product/")
        locale = request.POST.get("locale", "en")[:5]
        if locale not in ("en", "nl", "de"):
            locale = "en"
        niche_hint = request.POST.get("niche_hint", "").strip()[:300]
        job, created = create_pdp_job(shop, product_gid, locale, niche_hint)
        if created:
            from apps.generator.tasks import run_pdp_task

            run_pdp_task.delay(str(job.id))
            messages.success(request, "Generating product page — follow the progress below.")
        else:
            messages.info(request, "A generation for this product is already running.")
        return redirect(f"/app/jobs/{job.id}/")

    products = _fetch_products(shop)
    return render(
        request,
        "app/product_start.html",
        {
            "products": products,
            "shop_domain": shop.domain,
            "default_locale": getattr(request, "ui_locale", "en") or "en",
        },
    )


@require_http_methods(["GET"])
def job_status_view(request: HttpRequest, job_id) -> HttpResponse:
    """Step-by-step progress for one generation job (polls itself via meta refresh)."""
    from apps.generator.models import GenerationJob, Page

    shop = _get_shop(request)
    if shop is None:
        return _unauthorized()
    try:
        job = GenerationJob.objects.get(id=job_id, shop=shop)
    except GenerationJob.DoesNotExist:
        return HttpResponseForbidden("Not found")

    steps = list(job.steps.all())
    page = Page.objects.filter(job=job).first()
    terminal = job.status in TERMINAL_STATUSES
    return render(
        request,
        "app/job_status.html",
        {
            "job": job,
            "steps": steps,
            "page": page,
            "terminal": terminal,
            "is_running": not terminal,
        },
    )


def run_pdp_job(job_id: str) -> dict:
    """Execute a standalone PDP job end-to-end.

    Mirrors the store-build child behaviour (12 §5): whenever the job is
    waiting for an angle (needs_input) or failed because no angle was
    chosen yet (copy raises COPY_INPUT_MISSING), the best-matching angle
    is auto-selected, the copy step is reset and the job resumes — the
    merchant reviews the finished page in the editor, not mid-pipeline.
    """
    from apps.generator.models import GenerationJob, JobStatus, StepStatus
    from apps.generator.tasks import _auto_angle, execute_job

    result = execute_job(job_id)
    try:
        job = GenerationJob.objects.get(id=job_id)
    except GenerationJob.DoesNotExist:
        return result

    research = job.steps.filter(name="research", status="succeeded").first()
    angle_missing = research and research.output and not (
        (research.output or {}).get("chosen_angle") or (job.input or {}).get("angle_id")
    )
    if angle_missing and job.status in ("needs_input", "failed"):
        angles = (research.output or {}).get("angles") or []
        if angles:
            chosen_id = _auto_angle(job, angles)
            angle = next((a for a in angles if a.get("id") == chosen_id), angles[0])
            research.output["chosen_angle"] = angle
            research.save(update_fields=["output"])
            job.input["angle_id"] = angle.get("id")
            job.status = JobStatus.QUEUED
            job.current_step = None
            job.error_code = None
            job.error_message = None
            job.finished_at = None
            job.save(update_fields=[
                "input", "status", "current_step", "error_code", "error_message", "finished_at",
            ])
            job.steps.filter(status=StepStatus.FAILED).update(status=StepStatus.PENDING)
            result = execute_job(job_id)
    return result

