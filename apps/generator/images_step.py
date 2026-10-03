"""Image generation step — generates images via providers and uploads to Shopify.

See docs/05-ai-pipeline.md §4.4.
- F01-7: skips when the product has no own photos (merchant must upload at
  least 1 product photo before AI images are generated).
- Generates hero + lifestyle + detail images via Vertex/OpenAI
- Signs with C2PA (best-effort; skipped in dev without certificates)
- Uploads to Shopify Files (staged upload + fileCreate) and stores the
  resulting file GIDs in JobStep.output — layout copies them onto
  Page.images, publish writes the image_hero metaobject field from there.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.generator.models import GenerationJob, JobStep

logger = logging.getLogger(__name__)

# Image slots to generate (05 §4.4)
IMAGE_SLOTS = ["hero", "lifestyle_1", "lifestyle_2", "detail_1"]

# F01-7 merchant message when the product has no own photos
NO_OWN_MEDIA_MESSAGE = "Upload at least 1 product photo for AI images."


def _own_media(job: GenerationJob) -> list[str]:
    """Product photos the merchant owns: Shopify product media or a photo
    supplied on the manual/URL confirm form."""
    import_step = job.steps.filter(name="import").first()
    urls: list[str] = []
    if import_step and import_step.output:
        urls = list((import_step.output or {}).get("reference_image_urls") or [])
    manual = (job.input or {}).get("manual") or {}
    if manual.get("photo_url"):
        urls.append(manual["photo_url"])
    return urls


def run_images(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Generate images for the page.

    F01-7: no own product photos -> step is skipped with a merchant message
    (returning None; execute_job marks the step SKIPPED).
    """
    import base64  # noqa: F401  (kept for legacy debugging)
    import tempfile
    from pathlib import Path

    from apps.ai.c2pa import sign_image
    from apps.ai.image_providers import get_resolution_for_slot
    from apps.ai.image_upload import build_alt_text, upload_image

    # F01-7 — skip when the merchant has no own product photos
    if not _own_media(job):
        step.output = {
            "skipped": True,
            "message": NO_OWN_MEDIA_MESSAGE,
            "images": {},
            "errors": [],
            "generated": 0,
        }
        step.save(update_fields=["output"])
        logger.info("Images skipped for job %s: %s", job.id, NO_OWN_MEDIA_MESSAGE)
        return None

    # Load copy output
    copy_step = job.steps.filter(name="copy").first()
    if not copy_step or not copy_step.output:
        logger.warning("No copy output for job %s", job.id)
        return None

    sections_data = copy_step.output.get("sections") or []
    # Legacy checkpoints nested the payload under a second "sections" key
    sections = sections_data.get("sections") or [] if isinstance(sections_data, dict) else sections_data

    # Build prompts from sections
    prompts = _build_image_prompts(sections)

    # Generate + upload images
    uploaded: dict[str, dict[str, str]] = {}
    image_errors: list[str] = []
    alt_seed = _alt_seed(sections, job)

    for slot in IMAGE_SLOTS:
        prompt = prompts.get(slot)
        if not prompt:
            continue

        resolution = get_resolution_for_slot(slot)

        result = _generate_with_providers(prompt, resolution)

        if not result.success:
            image_errors.append(f"{slot}: {result.error}")
            continue

        # Sign with C2PA (writes to temp file, returns path; None on failure)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        signed_path = sign_image(result.image_bytes, tmp_path)

        # sign_image returns None on failure and writes NOTHING — fall back to
        # the original provider bytes (dev has no C2PA certificates; production
        # requires them, see C2PA action for Paul). Never upload the empty
        # temp file: GCS rejects it with EntityTooSmall (HTTP 400).
        if signed_path and Path(signed_path).exists() and Path(signed_path).stat().st_size > 0:
            with open(signed_path, "rb") as f:
                signed_bytes = f.read()
        else:
            logger.warning("C2PA signing unavailable for slot %s — uploading unsigned original", slot)
            signed_bytes = result.image_bytes

        Path(tmp_path).unlink(missing_ok=True)
        if signed_path and signed_path != tmp_path:
            Path(signed_path).unlink(missing_ok=True)

        # Upload to Shopify Files (staged upload + fileCreate, waits for READY)
        alt = build_alt_text(f"{alt_seed} — {slot.replace('_', ' ')}", locale=job.content_locale)
        up = upload_image(job.shop, signed_bytes, filename=f"mosaiq-{str(job.id)[:8]}-{slot}.png", alt=alt)
        if not up.success:
            image_errors.append(f"{slot}: upload failed: {up.error}")
            continue

        uploaded[slot] = {"gid": up.file_gid, "alt": alt}

    output = {
        "images": uploaded,
        "errors": image_errors,
        "generated": len(uploaded),
    }

    if not uploaded:
        raise RuntimeError(f"Image generation failed: {', '.join(image_errors)}")

    return output


def _alt_seed(sections: list[dict[str, Any]], job: GenerationJob) -> str:
    """Short product title for alt text."""
    for section in sections:
        if section.get("type") == "hero":
            return (section.get("headline") or "").strip() or "Product"
    page = job.pages.order_by("created_at").first()
    return (page.title if page else "Product") or "Product"


def _build_image_prompts(sections: list[dict[str, Any]]) -> dict[str, str]:
    """Build image generation prompts from page sections."""
    prompts = {}

    # Hero prompt from hero section
    for section in sections:
        if section.get("type") == "hero":
            headline = section.get("headline", "")
            subheadline = section.get("subheadline", "")
            prompts["hero"] = (
                f"Professional product photo: {headline}. {subheadline}. Clean background, studio lighting."
            )
            break

    # Default lifestyle prompts
    prompts.setdefault("lifestyle_1", "Lifestyle photo: product in use in a modern home setting. Natural lighting.")
    prompts.setdefault("lifestyle_2", "Lifestyle photo: product on a clean desk/table. Minimalist style.")
    prompts.setdefault("detail_1", "Close-up detail shot of the product. Show texture and quality.")

    return prompts


def _generate_with_providers(prompt: str, resolution: str) -> Any:
    """Try Vertex first, then OpenAI fallback."""
    import os

    from apps.ai.image_providers import OpenAIImageProvider, VertexImageProvider

    # Try Vertex
    try:
        vertex = VertexImageProvider()
        result = vertex.generate(prompt, resolution=resolution)
        if result.success:
            return result
        logger.warning("Vertex failed: %s", result.error)
    except Exception as exc:
        logger.warning("Vertex exception: %s", exc)

    # Fallback to OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        try:
            openai = OpenAIImageProvider(api_key=openai_key)
            result = openai.generate(prompt, resolution=resolution)
            if result.success:
                return result
            logger.warning("OpenAI failed: %s", result.error)
        except Exception as exc:
            logger.warning("OpenAI exception: %s", exc)

    # Return failure
    from apps.ai.image_providers import ImageGenerationResult

    return ImageGenerationResult(success=False, error="All providers failed")
