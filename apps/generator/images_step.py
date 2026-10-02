"""Image generation step — generates images via providers and uploads to Shopify.

See docs/05-ai-pipeline.md §4.4.
- Generates hero + lifestyle + detail images via Vertex/OpenAI
- Signs with C2PA
- Uploads to Shopify Files
- Stores image URLs in JobStep.output
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.generator.models import GenerationJob, JobStep

logger = logging.getLogger(__name__)

# Image slots to generate (05 §4.4)
IMAGE_SLOTS = ["hero", "lifestyle_1", "lifestyle_2", "detail_1"]


def run_images(job: GenerationJob, step: JobStep) -> dict[str, Any] | None:
    """Generate images for the page.

    1. Load copy output (sections) from checkpoint
    2. Build image prompts from sections
    3. Generate via providers (Vertex primary, OpenAI fallback)
    4. Sign with C2PA
    5. Upload to Shopify Files
    6. Store URLs in output
    """
    import base64
    import tempfile
    from pathlib import Path

    from apps.ai.c2pa import sign_image
    from apps.ai.image_providers import get_resolution_for_slot

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

    # Generate images
    image_urls: dict[str, str] = {}
    image_errors: list[str] = []

    for slot in IMAGE_SLOTS:
        prompt = prompts.get(slot)
        if not prompt:
            continue

        resolution = get_resolution_for_slot(slot)

        # Try providers
        result = _generate_with_providers(prompt, resolution)

        if not result.success:
            image_errors.append(f"{slot}: {result.error}")
            continue

        # Sign with C2PA (writes to temp file, returns path)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        signed_path = sign_image(result.image_bytes, tmp_path)

        # Read signed bytes (or original if signing failed)
        read_path = signed_path or tmp_path
        with open(read_path, "rb") as f:
            signed_bytes = f.read()

        # Cleanup temp files
        Path(tmp_path).unlink(missing_ok=True)
        if signed_path and signed_path != tmp_path:
            Path(signed_path).unlink(missing_ok=True)

        # Upload to Shopify (placeholder — real upload needs Shopify Files)
        # For now, store as base64 data URL (will be replaced with real CDN URLs)
        image_urls[slot] = f"data:image/png;base64,{base64.b64encode(signed_bytes).decode()}"

    output = {
        "images": image_urls,
        "errors": image_errors,
        "generated": len(image_urls),
    }

    if not image_urls:
        raise RuntimeError(f"Image generation failed: {', '.join(image_errors)}")

    return output


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
