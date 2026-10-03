"""Start with product — standalone PDP generation (F01 + F20).

The dashboard card "Start with product" lands here. The merchant picks
one of three sources (09 §25, F01-1):

1. **Existing product** — pick from the shop's products (paginated, 50/page,
   search on title, source label per product).
2. **Manual input** — title/description/price directly; a DRAFT product is
   created via productSet, then the pipeline runs.
3. **Public URL** — facts are extracted (own words, no verbatim copy),
   the job pauses on `needs_input` with a prefilled confirmation form
   (05 §4.1). After confirmation (price required) a manual product is
   created and the job continues.

Pipeline per source: import → research → copy → images → compliance_check
→ layout → publish. Reuse rules: an in-flight PDP job for the same source
redirects to its status page instead of creating a duplicate.
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
PRODUCTS_PER_PAGE = 50


def _get_shop(request: HttpRequest):
    from apps.core.models import Shop

    shop_domain = getattr(request, "shop_domain", None)
    return Shop.objects.filter(domain=shop_domain).first() if shop_domain else None


def _unauthorized() -> HttpResponse:
    return HttpResponseForbidden("Unauthorized")


def _api_version() -> str:
    return getattr(settings, "SHOPIFY_API_VERSION", "2026-07")


def _source_labels(shop) -> dict[str, str]:
    """Map product_gid → source label from ProductSource rows (fallback: vendor heuristic)."""
    from apps.sources.models import ProductSource

    labels: dict[str, str] = {}
    for ps in ProductSource.objects.filter(shop=shop):
        labels[ps.product_gid] = ps.get_source_display()
    return labels


def _fetch_products(shop, *, search: str = "", cursor: str | None = None) -> tuple[list[dict], str | None]:
    """Shop products via GraphQL with optional title search + cursor pagination (F01-1)."""
    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query

    try:
        token = decrypt_token(shop.access_token_encrypted)
        client = ShopifyGraphQLClient(shop.domain, token, _api_version())
        query = load_query("products_list_search")
        variables: dict = {"first": PRODUCTS_PER_PAGE}
        if cursor:
            variables["after"] = cursor
        if search:
            variables["query"] = f'title:{search}*'
        data = client.execute(query, variables)
        products_conn = data.get("products") or {}
        nodes = products_conn.get("nodes") or []
        next_cursor = None
        page_info = products_conn.get("pageInfo") or {}
        if page_info.get("hasNextPage"):
            next_cursor = page_info.get("endCursor")
        return nodes, next_cursor
    except Exception as exc:  # the picker must never 500
        logger.warning("products query failed for %s: %s", shop.domain, exc)
        return [], None


def create_pdp_job(shop, *, locale: str, niche_hint: str = "", product_gid: str | None = None,
                   manual: dict | None = None, source_url: str | None = None):
    """Create (or reuse) a standalone PDP job. Exactly one source is allowed (05 §3).

    Shared with the E2E demo script.
    """
    from apps.generator.models import GenerationJob, JobKind, JobStatus, PageType
    from apps.themes.models import BrandKit

    sources = [x for x in (product_gid, manual, source_url) if x]
    if len(sources) != 1:
        raise ValueError("Exactly one of product_gid, manual or source_url is required")

    # Reuse an in-flight job for the same source (idempotent on double-click)
    for existing in GenerationJob.objects.filter(
        kind=JobKind.PAGE, page_type=PageType.PDP, shop=shop, status__in=["queued", "running", "needs_input"]
    ):
        existing_input = existing.input or {}
        if product_gid and existing_input.get("product_gid") == product_gid:
            return existing, False
        if source_url and existing_input.get("source_url") == source_url:
            return existing, False
        if manual and existing_input.get("manual") == manual:
            return existing, False

    import contextlib
    import uuid as _uuid

    style_preset = "clean"
    with contextlib.suppress(Exception):  # BrandKit optional (research/copy degrade to defaults)
        style_preset = BrandKit.objects.get(shop=shop).style_preset or "clean"

    input_data: dict = {
        "content_locale": locale,
        "niche_hint": niche_hint,
        "style_preset": style_preset,
    }
    if product_gid:
        input_data["product_gid"] = product_gid
        job_key = f"pdp-{product_gid.rsplit('/', 1)[-1]}"
    elif manual:
        input_data["manual"] = manual
        job_key = f"pdp-manual-{_uuid.uuid4().hex[:8]}"
    else:
        input_data["source_url"] = source_url
        job_key = f"pdp-url-{_uuid.uuid4().hex[:8]}"

    job = GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type=PageType.PDP,
        content_locale=locale,
        status=JobStatus.QUEUED,
        idempotency_key=f"{job_key}-{_uuid.uuid4().hex[:8]}",
        input=input_data,
    )
    from apps.generator.models import JobStep

    for name in PDP_STEPS:
        JobStep.objects.get_or_create(job=job, name=name)
    return job, True


def _enqueue(job) -> None:
    from apps.generator.tasks import run_pdp_task

    run_pdp_task.delay(str(job.id))


@require_http_methods(["GET", "POST"])
def product_start_view(request: HttpRequest) -> HttpResponse:
    """Three-source picker → create PDP job → redirect to the job status page (09 §25)."""
    shop = _get_shop(request)
    if shop is None:
        return _unauthorized()

    if request.method == "POST":
        source = request.POST.get("source", "existing")
        locale = request.POST.get("locale", "en")[:5]
        if locale not in ("en", "nl", "de"):
            locale = "en"
        niche_hint = request.POST.get("niche_hint", "").strip()[:300]

        if source == "existing":
            product_gid = request.POST.get("product_gid", "").strip()
            if not product_gid.startswith("gid://shopify/Product/"):
                messages.error(request, "Select a product first.")
                return redirect("/app/start/product/")
            job, created = create_pdp_job(shop, locale=locale, niche_hint=niche_hint, product_gid=product_gid)

        elif source == "url":
            source_url = request.POST.get("source_url", "").strip()[:2000]
            if not source_url.startswith(("http://", "https://")):
                messages.error(request, "Enter a valid product URL.")
                return redirect("/app/start/product/")
            job, created = create_pdp_job(shop, locale=locale, niche_hint=niche_hint, source_url=source_url)

        else:  # manual
            title = request.POST.get("title", "").strip()[:120]
            description = request.POST.get("description", "").strip()[:5000]
            price = request.POST.get("price", "").strip()[:12] or None
            currency = request.POST.get("currency", "").strip()[:3] or None
            if len(title) < 3 or len(description) < 20:
                messages.error(request, "Title (min 3 characters) and description (min 20 characters) are required.")
                return redirect("/app/start/product/")
            manual = {"title": title, "description": description, "price": price, "currency": currency, "specs": {}}
            job, created = create_pdp_job(shop, locale=locale, niche_hint=niche_hint, manual=manual)

        if created:
            _enqueue(job)
            messages.success(request, "Generating product page — follow the progress below.")
        else:
            messages.info(request, "A generation for this source is already running.")
        return redirect(f"/app/jobs/{job.id}/")

    # GET: picker with search + pagination (F01-1)
    search = request.GET.get("q", "").strip()[:80]
    cursor = request.GET.get("after") or None
    products, next_cursor = _fetch_products(shop, search=search, cursor=cursor)
    labels = _source_labels(shop)
    for p in products:
        p["source_label"] = labels.get(p.get("id", ""), "Unknown")

    has_prev = bool(request.GET.get("after")) or bool(search)
    return render(
        request,
        "app/product_start.html",
        {
            "products": products,
            "next_cursor": next_cursor,
            "search": search,
            "has_prev": has_prev,
            "shop_domain": shop.domain,
            "default_locale": getattr(request, "ui_locale", "en") or "en",
        },
    )


@require_http_methods(["POST"])
def confirm_product_view(request: HttpRequest, job_id) -> HttpResponse:
    """Prefilled ManualProduct confirmation after URL import (05 §4.1, F01-5).

    Validates the form, writes the confirmed manual input onto the job,
    resets the import step and resumes the pipeline.
    """
    from apps.generator.models import GenerationJob, JobStatus, StepStatus

    shop = _get_shop(request)
    if shop is None:
        return _unauthorized()
    try:
        job = GenerationJob.objects.get(id=job_id, shop=shop)
    except GenerationJob.DoesNotExist:
        return HttpResponseForbidden("Not found")

    if job.status not in (JobStatus.NEEDS_INPUT, JobStatus.FAILED):
        messages.info(request, "This generation is not waiting for confirmation.")
        return redirect(f"/app/jobs/{job.id}/")

    title = request.POST.get("title", "").strip()[:120]
    description = request.POST.get("description", "").strip()[:5000]
    price = request.POST.get("price", "").strip()[:12]
    currency = request.POST.get("currency", "").strip()[:3] or None

    if len(title) < 3:
        messages.error(request, "Title must be at least 3 characters.")
        return redirect(f"/app/jobs/{job.id}/")
    if len(description) < 20:
        messages.error(request, "Description must be at least 20 characters.")
        return redirect(f"/app/jobs/{job.id}/")
    if not price:
        messages.error(request, "A price is required to create the product.")
        return redirect(f"/app/jobs/{job.id}/")

    # Carry over specs extracted from the URL (facts only)
    import_step = job.steps.filter(name="import").first()
    prefill = (import_step.output or {}).get("prefill", {}) if import_step and import_step.output else {}
    specs = prefill.get("specs", {}) if isinstance(prefill.get("specs"), dict) else {}

    job.input["manual"] = {
        "title": title,
        "description": description,
        "specs": specs,
        "price": price,
        "currency": currency,
    }
    job.input.pop("source_url", None)  # import re-runs on the confirmed manual product
    job.status = JobStatus.QUEUED
    job.error_code = None
    job.error_message = None
    job.save(update_fields=["input", "status", "error_code", "error_message"])
    job.steps.filter(name="import").update(status=StepStatus.PENDING, output=None)

    _enqueue(job)
    messages.success(request, "Product confirmed — generation continues.")
    return redirect(f"/app/jobs/{job.id}/")


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
    is_running = job.status not in TERMINAL_STATUSES

    # Prefill data for the URL-confirmation form (F01-5)
    prefill = {}
    import_step = next((s for s in steps if s.name == "import"), None)
    if job.status == "needs_input" and import_step and import_step.output:
        prefill = (import_step.output or {}).get("prefill", {}) or {}

    page = Page.objects.filter(job=job).first()

    return render(
        request,
        "app/job_status.html",
        {
            "job": job,
            "steps": steps,
            "is_running": is_running,
            "prefill": prefill,
            "page": page,
        },
    )


def run_pdp_job(job_id: str) -> dict:
    """Execute a standalone PDP job end-to-end.

    Mirrors the store-build child behaviour (12 §5): whenever the job is
    waiting for an angle (needs_input after research), the best-matching
    angle is auto-selected, the job resets and resumes — the merchant
    reviews the finished page in the editor, not mid-pipeline.

    Jobs paused on `needs_input` after the import step (URL confirmation)
    are left untouched — the merchant must confirm via the form first.
    """
    from apps.generator.models import GenerationJob, JobStatus
    from apps.generator.tasks import _auto_angle, execute_job

    result = execute_job(job_id)
    try:
        job = GenerationJob.objects.get(id=job_id)
    except GenerationJob.DoesNotExist:
        return result

    if job.status != JobStatus.NEEDS_INPUT:
        return result

    research = job.steps.filter(name="research", status="succeeded").first()
    if not research or not research.output:
        return result  # needs_input from import (URL confirm) or another step — do not auto-resume

    angles = (research.output or {}).get("angles") or []
    angle_missing = not (
        (research.output or {}).get("chosen_angle") or (job.input or {}).get("angle_id")
    )
    if angles and angle_missing:
        chosen_id = _auto_angle(job, angles)
        angle = next((a for a in angles if a.get("id") == chosen_id), angles[0])
        research.output["chosen_angle"] = angle
        research.save(update_fields=["output"])
        job.input["angle_id"] = angle.get("id")
        job.status = JobStatus.QUEUED
        job.current_step = None
        job.save(update_fields=["input", "status", "current_step"])
        result = execute_job(job_id)
    return result
