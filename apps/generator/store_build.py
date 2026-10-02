"""Store build — the F15 wizard's `store_build` job (12 §5, §7, F15-10/15).

The parent job does no AI work itself. Its four steps:

1. ``import``   — reserve plan limits in ONE transaction
                  (``store_generations`` = 1 + (n_pdps − 1), ``ai_images``
                  per PDP; 12 §7). Recorded in ``ManagedResource``-less
                  bookkeeping: ``StoreBlueprint.store_limit_reserved_at``.
2. ``research`` — create the structure's collections via
                  ``collectionCreate`` (unpublished — publishing happens at
                  go-live, T-118) and store each one as ``ManagedResource``.
3. ``copy``     — create the child jobs: one ``page`` job per standard
                  page type with content, one ``home`` job, and one ``pdp``
                  job per selected product (max 3 concurrent handled by the
                  queue). Children run the generic ``run_job`` pipeline via
                  ``run_store_build_child``.
4. ``publish``  — create the ``mosaiq-main`` menu once ALL children have a
                  Shopify page GID (``menuUpdate`` if it already exists).

Idempotency (F15-15): collections/pages are looked up via
``ManagedResource`` first; child jobs are ``get_or_create`` on a fixed
idempotency key; the parent job itself is keyed ``store-build-<blueprint>``.
"""

from __future__ import annotations

import contextlib
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.shopify_client import load_query
from apps.generator.models import (
    GenerationJob,
    JobKind,
    JobStatus,
    JobStep,
    ManagedResource,
    Page,
    PageStatus,
    PageType,
    StepStatus,
    StoreBlueprint,
)

logger = logging.getLogger(__name__)

STORE_JOB_KEY = "store-build-{bp_id}"
PAGE_JOB_KEY = "bp-page-{bp_id}-{page_type}"
PDP_JOB_KEY = "bp-pdp-{bp_id}-{gid_suffix}"
MENU_HANDLE = "mosaiq-main"
PARENT_STEPS = ["import", "research", "copy", "publish"]
PDP_STEPS = ["import", "research", "copy", "images", "compliance_check", "layout", "publish"]
STANDARD_PAGE_STEPS = ["layout", "publish"]
# Menu display order for standard pages (12 §2 menu: Home → collections → pages)
PAGE_MENU_ORDER = ["shipping", "returns", "faq", "about"]


def _get_client(shop):
    from django.conf import settings

    from apps.core.shopify_client import ShopifyGraphQLClient
    from apps.core.tokens import decrypt_token

    return ShopifyGraphQLClient(
        shop.domain,
        decrypt_token(shop.access_token_encrypted),
        settings.SHOPIFY_API_VERSION,
    )


def get_or_create_store_job(shop, bp) -> GenerationJob:
    """The parent store_build job — one per blueprint (F15-15)."""
    key = STORE_JOB_KEY.format(bp_id=bp.id)
    job, created = GenerationJob.objects.get_or_create(
        shop=shop,
        kind=JobKind.STORE,
        idempotency_key=key,
        defaults={
            "page_type": None,
            "content_locale": (bp.content_locales or ["en"])[0],
            "input": {
                "blueprint_id": str(bp.id),
                "product_gids": list(bp.selected_product_gids or []),
                "usage_reserved": True,
            },
            "status": JobStatus.QUEUED,
        },
    )
    return job


def ensure_parent_steps(job: GenerationJob) -> None:
    for name in PARENT_STEPS:
        JobStep.objects.get_or_create(job=job, name=name)


def ensure_child_steps(job: GenerationJob, names: list[str]) -> None:
    for name in names:
        JobStep.objects.get_or_create(job=job, name=name)


def _mark_step(step: JobStep, status: str, output: dict | None = None, error: str | None = None) -> None:
    step.status = status
    if output is not None or error is not None:
        payload = dict(step.output or {})
        if error is not None:
            payload["last_error"] = error
        if output is not None:
            payload.update(output)
        step.output = payload
    if status in (StepStatus.SUCCEEDED, StepStatus.FAILED):
        step.finished_at = timezone.now()
        step.save(update_fields=["status", "output", "finished_at"])
    else:
        step.save(update_fields=["status", "output"])


# ── Step 1: limits ─────────────────────────────────────────────────────────


def reserve_build_limits(bp) -> tuple[bool, dict, str]:
    """12 §7: reserve store_generations + ai_images in ONE transaction."""
    from apps.billing.limits import reserve

    gids = list(bp.selected_product_gids or [])
    n_pdps = len(gids)
    store_generations = 1 + max(0, n_pdps - 1)
    ai_images = n_pdps

    with transaction.atomic():
        r1 = reserve(bp.shop, "store_generations", store_generations)
        if not r1.allowed:
            return False, {}, r1.message
        r2 = reserve(bp.shop, "ai_images", ai_images)
        if not r2.allowed:
            # roll back the first reservation
            from apps.billing.limits import release

            release(bp.shop, "store_generations", store_generations)
            return False, {}, r2.message

    bp.store_limit_reserved_at = bp.store_limit_reserved_at or timezone.now()
    bp.save(update_fields=["store_limit_reserved_at", "updated_at"])
    _BUILD_RESERVATIONS[str(bp.id)] = {"store_generations": store_generations, "ai_images": ai_images}
    return True, {"store_generations": store_generations, "ai_images": ai_images}, ""


# Reservations are recorded in process memory for the consume/release step;
# the authoritative record is the UsageCounter deltas themselves.
_BUILD_RESERVATIONS: dict[str, dict] = {}


def convert_reservation(bp, consume_ok: bool) -> None:
    """Consume on final success, release on terminal failure."""
    from apps.billing.limits import consume, release

    amounts = _BUILD_RESERVATIONS.pop(str(bp.id), None)
    if amounts is None:
        # Recompute from the blueprint (fresh process)
        n_pdps = len(bp.selected_product_gids or [])
        amounts = {"store_generations": 1 + max(0, n_pdps - 1), "ai_images": n_pdps}
    if consume_ok:
        consume(bp.shop, "store_generations", amounts["store_generations"])
        consume(bp.shop, "ai_images", amounts["ai_images"])
    else:
        release(bp.shop, "store_generations", amounts["store_generations"])
        release(bp.shop, "ai_images", amounts["ai_images"])


# ── Step 2: collections ────────────────────────────────────────────────────


def create_collections(client, bp) -> dict[str, str]:
    """Create the structure's collections (unpublished) → ManagedResource."""
    created: dict[str, str] = {}
    for collection in (bp.store_structure or {}).get("collections", []):
        title = collection.get("title", "")
        handle = slugify(title)[:255]
        existing = ManagedResource.objects.filter(
            shop=bp.shop, kind=ManagedResource.Kind.COLLECTION, handle=handle, removed_at__isnull=True
        ).first()
        if existing:
            created[title] = existing.gid
            continue

        gids = collection.get("product_gids", [])
        variables = {
            "collection": {
                "title": title,
                "descriptionHtml": f"<p>{collection.get('description', '')}</p>",
                "handle": handle,
                "sources": [
                    {
                        "source": {
                            "title": "Mosaiq",
                            "inclusion": {
                                "matchType": "ANY",
                                "selections": [{"productId": gid} for gid in gids],
                            },
                        }
                    }
                ],
            }
        }
        data = client.execute(load_query("collection_create"), variables=variables)
        errors = (data.get("collectionCreate") or {}).get("userErrors") or []
        if errors:
            raise RuntimeError(f"collectionCreate failed: {errors[0].get('message')}")
        gid = (data.get("collectionCreate") or {}).get("collection", {}).get("id")
        if not gid:
            raise RuntimeError("collectionCreate returned no collection")
        ManagedResource.objects.create(
            shop=bp.shop,
            blueprint=bp,
            kind=ManagedResource.Kind.COLLECTION,
            gid=gid,
            handle=handle,
            title=title,
        )
        created[title] = gid

    structure = bp.store_structure or {}
    structure["created"] = {**structure.get("created", {}), "collections": created}
    bp.store_structure = structure
    bp.save(update_fields=["store_structure", "updated_at"])
    return created


# ── Step 3: child jobs ─────────────────────────────────────────────────────


def _get_or_create_child(bp, store_job, key: str, **defaults) -> GenerationJob:
    job, _ = GenerationJob.objects.get_or_create(
        shop=bp.shop,
        kind=JobKind.PAGE,
        parent=store_job,
        idempotency_key=key,
        defaults={
            "content_locale": (bp.content_locales or ["en"])[0],
            "status": JobStatus.QUEUED,
            **defaults,
        },
    )
    return job


PRODUCT_PIPELINE_STEPS = ["import", "research", "copy", "images", "compliance_check"]


def _skip_product_pipeline_steps(job: GenerationJob) -> None:
    """Standard-page/home children run layout+publish only.

    ``get_pending_steps`` auto-creates the full page chain, which would
    otherwise run the product pipeline (import fails without a product).
    Pre-create those steps as SKIPPED so the checkpoint logic ignores them.
    """
    for name in PRODUCT_PIPELINE_STEPS:
        JobStep.objects.get_or_create(
            job=job,
            name=name,
            defaults={"status": StepStatus.SKIPPED},
        )


def _local_page_for(bp, job: GenerationJob, page_type: str, title: str, sections: list[dict]) -> Page:
    locale = (bp.content_locales or ["en"])[0]
    page, _ = Page.objects.get_or_create(
        job=job,
        page_type=page_type,
        defaults={
            "shop": bp.shop,
            "content_locale": locale,
            "status": PageStatus.DRAFT,
            "title": title,
            "sections": {locale: {"sections": sections, "seo_title": title}},
            "version": 1,
        },
    )
    return page


def create_children(bp, store_job) -> tuple[list[GenerationJob], list[str]]:
    """Standard-page + home children (local Page + layout/publish) and PDP
    children (full pipeline). Enqueued by the caller via run_store_build_child."""
    locale = (bp.content_locales or ["en"])[0]
    children: list[GenerationJob] = []
    skipped: list[str] = []

    # Standard pages that actually have generated content
    standard = bp.standard_pages or {}
    for page_type, entry in standard.items():
        sections = entry.get("sections") or []
        if not sections or entry.get("warnings") == ["not_generated"]:
            skipped.append(page_type)
            continue
        job = _get_or_create_child(
            bp,
            store_job,
            PAGE_JOB_KEY.format(bp_id=bp.id, page_type=page_type),
            page_type=page_type,
            input={"blueprint_id": str(bp.id), "content_locale": locale, "usage_reserved": True},
        )
        ensure_child_steps(job, STANDARD_PAGE_STEPS)
        _skip_product_pipeline_steps(job)
        _local_page_for(bp, job, page_type, entry.get("title") or page_type.title(), sections)
        children.append(job)

    # Home page — built from the BrandKit + brief (real data, no AI copy yet;
    # the T-060x copy step upgrades it later).
    home_job = _get_or_create_child(
        bp,
        store_job,
        PAGE_JOB_KEY.format(bp_id=bp.id, page_type="home"),
        page_type=PageType.HOME,
        input={"blueprint_id": str(bp.id), "content_locale": locale, "usage_reserved": True},
    )
    ensure_child_steps(home_job, STANDARD_PAGE_STEPS)
    _skip_product_pipeline_steps(home_job)
    if not Page.objects.filter(job=home_job).exists():

        tagline = ""
        with contextlib.suppress(Exception):
            tagline = bp.shop.brand_kit.tagline or ""
        hero = {
            "type": "hero",
            "headline": bp.brand_name or "",
            "subheadline": tagline or (bp.description or ""),
            "cta_label": "Shop now",
        }
        _local_page_for(bp, home_job, "home", bp.brand_name or "Home", [hero])
    children.append(home_job)

    # PDP children — one per selected product, full pipeline
    for gid in bp.selected_product_gids or []:
        job = _get_or_create_child(
            bp,
            store_job,
            PDP_JOB_KEY.format(bp_id=bp.id, gid_suffix=str(gid).rsplit("/", 1)[-1]),
            page_type=PageType.PDP,
            input={
                "blueprint_id": str(bp.id),
                "product_gid": gid,
                "content_locale": locale,
                "niche_hint": bp.description or "",
                "style_preset": (bp.brand_proposal or {}).get("style_preset") or "clean",
                "usage_reserved": True,
            },
        )
        ensure_child_steps(job, PDP_STEPS)
        children.append(job)

    return children, skipped


# ── Step 4: menu ───────────────────────────────────────────────────────────


def build_menu_items(bp) -> list[dict]:
    """FRONTPAGE + collections + pages (12 §4 menu_create)."""
    items: list[dict] = [{"title": "Home", "type": "FRONTPAGE", "resourceId": None}]

    collections = ManagedResource.objects.filter(
        shop=bp.shop, blueprint=bp, kind=ManagedResource.Kind.COLLECTION, removed_at__isnull=True
    )
    page_titles = {pt: (bp.standard_pages or {}).get(pt, {}).get("title", pt.title()) for pt in PAGE_MENU_ORDER}
    home_page = (
        Page.objects.filter(page_type="home", job__parent=bp.build_job).first()
        if bp.build_job_id
        else None
    )
    if home_page:
        page_titles["home"] = home_page.title
    ordered_types = ["home", *PAGE_MENU_ORDER]
    pages = {
        pt: ManagedResource.objects.filter(
            shop=bp.shop,
            blueprint=bp,
            kind=ManagedResource.Kind.PAGE,
            handle__icontains=f"-{pt}",
            removed_at__isnull=True,
        ).first()
        for pt in ordered_types
    }

    for mr in collections:
        items.append({"title": mr.title or mr.handle, "type": "COLLECTION", "resourceId": mr.gid})
    for pt in ordered_types:
        mr = pages.get(pt)
        if mr:
            items.append({"title": page_titles.get(pt, pt.title()), "type": "PAGE", "resourceId": mr.gid})
    return items


def create_menu(client, bp) -> str:
    """menuCreate/menuUpdate for mosaiq-main — idempotent via ManagedResource."""
    items = build_menu_items(bp)
    existing = ManagedResource.objects.filter(
        shop=bp.shop, kind=ManagedResource.Kind.MENU, handle=MENU_HANDLE, removed_at__isnull=True
    ).first()
    if existing:
        data = client.execute(
            load_query("menu_update"),
            variables={"id": existing.gid, "title": "Mosaiq", "items": items},
        )
        errors = (data.get("menuUpdate") or {}).get("userErrors") or []
        menu = (data.get("menuUpdate") or {}).get("menu") or {}
    else:
        data = client.execute(
            load_query("menu_create"),
            variables={"title": "Mosaiq", "handle": MENU_HANDLE, "items": items},
        )
        errors = (data.get("menuCreate") or {}).get("userErrors") or []
        menu = (data.get("menuCreate") or {}).get("menu") or {}
        if not errors and menu.get("id"):
            ManagedResource.objects.create(
                shop=bp.shop, blueprint=bp, kind=ManagedResource.Kind.MENU, gid=menu["id"], handle=MENU_HANDLE
            )
    if errors:
        raise RuntimeError(f"menu mutation failed: {errors[0].get('message')}")
    return menu.get("id", "")


# ── Child completion → parent advance ──────────────────────────────────────


def children_state(store_job: GenerationJob) -> dict:
    children = GenerationJob.objects.filter(parent=store_job)
    return {
        "total": children.count(),
        "succeeded": children.filter(status=JobStatus.SUCCEEDED).count(),
        "failed": children.filter(status=JobStatus.FAILED).count(),
        "running": children.filter(status__in=[JobStatus.RUNNING, JobStatus.QUEUED]).count(),
    }


def advance_store_build(store_job: GenerationJob) -> None:
    """Called after each child finishes: run the menu step when ALL children
    succeeded (parent succeeds); a failed child keeps the parent running."""
    state = children_state(store_job)
    if state["total"] == 0 or state["running"] > 0 or state["failed"] > 0:
        return

    bp = None
    blueprint_id = (store_job.input or {}).get("blueprint_id")
    if blueprint_id:
        bp = StoreBlueprint.objects.filter(id=blueprint_id).first()

    menu_step = store_job.steps.get(name="publish")
    if menu_step.status == StepStatus.SUCCEEDED:
        return

    try:
        client = _get_client(store_job.shop)
        menu_gid = create_menu(client, bp) if bp is not None else ""
        _mark_step(menu_step, StepStatus.SUCCEEDED, output={"menu_gid": menu_gid})
        store_job.status = JobStatus.SUCCEEDED
        store_job.finished_at = timezone.now()
        store_job.save(update_fields=["status", "finished_at"])
        if bp is not None:
            convert_reservation(bp, consume_ok=True)
        logger.info("Store build %s succeeded; menu %s", store_job.id, menu_gid)
    except Exception as exc:  # noqa: BLE001 — surface as step failure
        _mark_step(menu_step, StepStatus.FAILED, error=str(exc))
        logger.error("Store build %s menu step failed: %s", store_job.id, exc)


# ── Page ManagedResources ──────────────────────────────────────────────────


def register_page_resources(blueprint_id) -> None:
    """Record every built Shopify page as ManagedResource (12 §2.3, F15-15).

    Called after each child job succeeds; the menu step reads these rows.
    """
    bp = StoreBlueprint.objects.filter(id=blueprint_id).first()
    if bp is None:
        return
    if bp.build_job_id is None:
        return
    pages = Page.objects.filter(job__parent=bp.build_job).exclude(shopify_page_gid__isnull=True).exclude(
        shopify_page_gid=""
    )
    for page in pages:
        handle = f"mq-{page.page_type}-{str(page.id)[:8]}-{page.content_locale}"
        ManagedResource.objects.get_or_create(
            shop=bp.shop,
            gid=page.shopify_page_gid,
            defaults={
                "blueprint": bp,
                "kind": ManagedResource.Kind.PAGE,
                "handle": handle,
                "title": page.title,
            },
        )
