"""Image providers — Vertex AI (primary) + OpenAI (fallback).

See docs/05-ai-pipeline.md §4.4, docs/00-decisions.md.
Primary: gemini-3.1-flash-image via Vertex AI on EU endpoint.
Fallback: gpt-image-2.5-sunburst via OpenAI /v1/images/edits.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Resolution presets (05 §4.4)
RESOLUTION_2K = "2048x2048"  # hero, lifestyle_*
RESOLUTION_1K = "1024x1024"  # detail_*

# Image slots that get 2K resolution
HIGH_RES_SLOTS = {"hero", "lifestyle_1", "lifestyle_2", "lifestyle_3"}


@dataclass
class ImageGenerationResult:
    """Result from an image provider."""

    success: bool
    image_bytes: bytes = b""
    provider: str = ""
    model: str = ""
    error: str = ""
    cost_usd: float = 0.0


def get_resolution_for_slot(slot: str) -> str:
    """Get resolution for an image slot."""
    return RESOLUTION_2K if slot in HIGH_RES_SLOTS else RESOLUTION_1K


class VertexImageProvider:
    """Vertex AI image provider (gemini-3.1-flash-image)."""

    MODEL = "gemini-3.1-flash-image"
    ENDPOINT = "europe-west4"

    def __init__(self, credentials: Any = None):
        self._credentials = credentials

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        resolution: str = RESOLUTION_2K,
    ) -> ImageGenerationResult:
        """Generate an image via Vertex AI.

        Args:
            prompt: Image generation prompt
            reference_images: Up to 4 own product photos
            resolution: Target resolution

        Returns:
            ImageGenerationResult
        """
        try:
            from google import genai

            client = genai.Client(
                vertexai=True,
                project="mosaiq-project",
                location=self.ENDPOINT,
            )

            # Build request contents
            contents: list[Any] = [prompt]

            # Add reference images (max 4)
            if reference_images:
                for ref in reference_images[:4]:
                    import io

                    import PIL.Image

                    img = PIL.Image.open(io.BytesIO(ref))
                    contents.append(img)

            response = client.models.generate_content(
                model=self.MODEL,
                contents=contents,
            )

            # Extract image from response
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        return ImageGenerationResult(
                            success=True,
                            image_bytes=base64.b64decode(part.inline_data.data),
                            provider="vertex",
                            model=self.MODEL,
                        )

            return ImageGenerationResult(
                success=False,
                provider="vertex",
                model=self.MODEL,
                error="No image in response",
            )

        except Exception as e:
            logger.warning("Vertex image generation failed: %s", e)
            return ImageGenerationResult(
                success=False,
                provider="vertex",
                model=self.MODEL,
                error=str(e),
            )


class OpenAIImageProvider:
    """OpenAI image provider (gpt-image-2.5-sunburst) as fallback."""

    MODEL = "gpt-image-2.5-sunburst"

    def __init__(self, api_key: str):
        self._api_key = api_key

    @staticmethod
    def model_name() -> str:
        from django.conf import settings

        return getattr(settings, "IMAGE_MODEL_FALLBACK", None) or OpenAIImageProvider.MODEL

    def generate(
        self,
        prompt: str,
        reference_images: list[bytes] | None = None,
        resolution: str = RESOLUTION_2K,
    ) -> ImageGenerationResult:
        """Generate an image via OpenAI.

        Args:
            prompt: Image generation prompt
            reference_images: Up to 4 own product photos
            resolution: Target resolution

        Returns:
            ImageGenerationResult
        """
        try:
            import httpx

            headers = {"Authorization": f"Bearer {self._api_key}"}

            # Parse resolution
            size = resolution  # "2048x2048" or "1024x1024"

            # Build multipart form
            files = []
            data = {
                "model": self.MODEL,
                "prompt": prompt,
                "size": size,
                "input_fidelity": "high",
                "n": "1",
            }

            # Add reference images
            if reference_images:
                for idx, ref in enumerate(reference_images[:4]):
                    files.append(
                        (
                            f"image[{idx}]",
                            (f"ref_{idx}.png", ref, "image/png"),
                        )
                    )

            # The gpt-image family only accepts 1024x1024 / 1536x1024 /
            # 1024x1536 — map the 2K preset to the landscape size.
            api_size = size if size in ("1024x1024", "1536x1024", "1024x1536") else "1536x1024"
            data["size"] = api_size
            data["model"] = self.model_name()

            if files:
                # Reference images require the multipart edits endpoint.
                response = httpx.post(
                    "https://api.openai.com/v1/images/edits",
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=120.0,
                )
            else:
                # Pure text-to-image: JSON generations endpoint (the edits
                # endpoint rejects non-multipart bodies — live lesson).
                json_body = {k: v for k, v in data.items() if k != "input_fidelity"}
                response = httpx.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={**headers, "Content-Type": "application/json"},
                    json=json_body,
                    timeout=120.0,
                )

            if response.status_code != 200:
                return ImageGenerationResult(
                    success=False,
                    provider="openai",
                    model=self.MODEL,
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

            result = response.json()
            if result.get("data") and result["data"][0].get("b64_json"):
                return ImageGenerationResult(
                    success=True,
                    image_bytes=base64.b64decode(result["data"][0]["b64_json"]),
                    provider="openai",
                    model=self.MODEL,
                )

            return ImageGenerationResult(
                success=False,
                provider="openai",
                model=self.MODEL,
                error="No image in response",
            )

        except Exception as e:
            logger.warning("OpenAI image generation failed: %s", e)
            return ImageGenerationResult(
                success=False,
                provider="openai",
                model=self.MODEL,
                error=str(e),
            )


def get_provider(provider_name: str, api_key: str = "") -> Any:
    """Get an image provider by name."""
    if provider_name == "vertex":
        return VertexImageProvider()
    elif provider_name == "openai":
        return OpenAIImageProvider(api_key=api_key)
    raise ValueError(f"Unknown provider: {provider_name}")
