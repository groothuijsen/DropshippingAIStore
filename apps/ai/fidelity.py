"""Image fidelity check — verifies generated image matches reference product.

See docs/05-ai-pipeline.md §4.4, docs/specs/F04-images.md criterion 3.
Uses Anthropic vision (LLM_MODEL_CHECK) to compare generated vs reference.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Max retries for fidelity check (04 criterion 3)
MAX_FIDELITY_ATTEMPTS = 2

# Max issues in FidelityResult
MAX_ISSUES = 10


@dataclass
class FidelityResult:
    """Result of a fidelity check."""

    same_product: bool
    issues: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        """Check if fidelity passed."""
        return self.same_product and not self.error


def check_fidelity(
    reference_image: bytes,
    generated_image: bytes,
    shop: Any = None,
) -> FidelityResult:
    """Check if generated image matches the reference product.

    Uses Anthropic vision to compare shape, color, logos, number of parts.

    Args:
        reference_image: Original product photo (bytes)
        generated_image: AI-generated image (bytes)
        shop: Shop instance (for AI client credentials)

    Returns:
        FidelityResult
    """
    try:
        import base64

        from apps.ai.anthropic_client import AnthropicClient
        from apps.ai.schemas import FidelityResult as FidelityResultSchema

        reference_b64 = base64.b64encode(reference_image).decode("utf-8")
        generated_b64 = base64.b64encode(generated_image).decode("utf-8")

        system_prompt = (
            "You are a product fidelity checker. Compare the generated image "
            "with the reference image. Answer JSON: {same_product: bool, issues: [...]}. "
            "same_product is true only if the product shape, color, logos, and "
            "number of parts match the reference."
        )

        user_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": reference_b64,
                },
            },
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": generated_b64,
                },
            },
            {
                "type": "text",
                "text": "Compare the first image (reference) with the second image (generated). "
                "Does this show the same product? Answer JSON: {same_product: bool, issues: [...]}. "
                "Issues should list specific differences (shape, color, logos, parts).",
            },
        ]

        # Use lower-level client with multimodal content
        client = AnthropicClient()
        result, _usage = client.call(
            model="claude-sonnet-4-5-20250929",
            system=system_prompt,
            user=user_content,
            schema=FidelityResultSchema,
            tool_name="submit_fidelity",
        )

        # Cap issues at MAX_ISSUES
        if len(result.issues) > MAX_ISSUES:
            result.issues = result.issues[:MAX_ISSUES]

        return FidelityResult(
            same_product=result.same_product,
            issues=result.issues,
        )

    except Exception as e:
        logger.warning("Fidelity check failed: %s", e)
        return FidelityResult(
            same_product=False,
            error=str(e),
        )


def check_and_retry(
    reference_image: bytes,
    generated_image: bytes,
    generate_fn: Any,
    shop: Any = None,
) -> tuple[bool, bytes, FidelityResult]:
    """Check fidelity with one retry on failure.

    Args:
        reference_image: Original product photo
        generated_image: First AI-generated image
        generate_fn: Callable that generates a new image (returns bytes)
        shop: Shop instance

    Returns:
        (passed, final_image_bytes, fidelity_result)
    """
    # First attempt
    result = check_fidelity(reference_image, generated_image, shop=shop)
    if result.passed:
        return True, generated_image, result

    # One retry
    logger.info("Fidelity check failed, retrying once. Issues: %s", result.issues)
    try:
        retry_image = generate_fn()
        result2 = check_fidelity(reference_image, retry_image, shop=shop)
        if result2.passed:
            return True, retry_image, result2
        return False, b"", result2
    except Exception as e:
        logger.warning("Fidelity retry failed: %s", e)
        return (
            False,
            b"",
            FidelityResult(
                same_product=False,
                error=str(e),
            ),
        )
