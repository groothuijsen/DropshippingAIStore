"""Error codes for the generator pipeline.

See docs/05-ai-pipeline.md §5.
Merchant-facing translations live in the i18n files (locale/).
"""

from __future__ import annotations


class GeneratorError(Exception):
    """Base exception for generator pipeline errors."""

    code: str = ""
    merchant_message: str = ""

    def __init__(self, code: str | None = None, message: str = ""):
        self.code = code or self.code
        super().__init__(message or self.merchant_message)


class ImportNotFound(GeneratorError):  # noqa: N818
    code = "IMPORT_NOT_FOUND"
    merchant_message = "This product no longer exists in your store."


class ImportSourceBlocked(GeneratorError):  # noqa: N818
    code = "IMPORT_SOURCE_BLOCKED"
    merchant_message = "We couldn't read this link. Please enter the product details manually."


class AiSchemaInvalid(GeneratorError):  # noqa: N818
    code = "AI_SCHEMA_INVALID"
    merchant_message = "Generation failed. Please try again; you have not been charged."


class AiProviderError(GeneratorError):
    code = "AI_PROVIDER_ERROR"
    merchant_message = "The AI service is temporarily unavailable. We'll retry automatically."


class AiBudgetExceeded(GeneratorError):  # noqa: N818
    code = "AI_BUDGET_EXCEEDED"
    merchant_message = "This request was too large. Try fewer pages at a time."


class ImageFidelityRejected(GeneratorError):  # noqa: N818
    code = "IMAGE_FIDELITY_REJECTED"
    merchant_message = "One or more images did not look enough like your product and have been left out."


class ComplianceBlocked(GeneratorError):  # noqa: N818
    code = "COMPLIANCE_BLOCKED"
    merchant_message = "Edit the highlighted text before you publish."


class GpsrIncomplete(GeneratorError):  # noqa: N818
    code = "GPSR_INCOMPLETE"
    merchant_message = "Fill in the manufacturer and safety details to be able to publish."


class PlanLimitReached(GeneratorError):  # noqa: N818
    code = "PLAN_LIMIT_REACHED"
    merchant_message = "You have reached your plan's limit. Upgrade or wait for the new period."


class ShopifyUserError(GeneratorError):
    code = "SHOPIFY_USER_ERROR"
    merchant_message = "Shopify rejected the change."


class ShopifyThrottled(GeneratorError):  # noqa: N818
    code = "SHOPIFY_THROTTLED"
    merchant_message = "Shopify is busy. We'll try again in a few minutes."


# ── Cost budget ───────────────────────────────────────────────────────────

AI_COST_BUDGET_USD = 2.00  # Per job (05 §2.6)
AI_COST_ALERT_USD_PER_STORE = 10.00  # Per store over 24h (11-ops)


def check_job_budget(job_cost_usd) -> None:
    """Raise AiBudgetExceeded if the job cost exceeds the budget."""
    from decimal import Decimal

    if job_cost_usd >= Decimal(str(AI_COST_BUDGET_USD)):
        raise AiBudgetExceeded(message=f"Job cost ${job_cost_usd} exceeded budget ${AI_COST_BUDGET_USD}")


class CopyInputMissing(GeneratorError):  # noqa: N818
    code = "COPY_INPUT_MISSING"
    merchant_message = "Research input is incomplete for this page. Retry the step."


class PageNotFound(GeneratorError):  # noqa: N818
    code = "PAGE_NOT_FOUND"
    merchant_message = "The page record is missing for this job. Retry the step."
