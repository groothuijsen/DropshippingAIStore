"""Import step — runs the import step of the pipeline.

See docs/05-ai-pipeline.md §4.1, docs/specs/F01-import.md.

Handles three input types:
- product_gid: fetch existing product via GraphQL
- manual: create manual product via productSet
- source_url: fetch URL, extract facts via AI, set needs_input
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.core.shopify_client import ShopifyGraphQLClient

if TYPE_CHECKING:
    from apps.core.models import Shop
    from apps.generator.models import GenerationJob

logger = logging.getLogger(__name__)

USER_AGENT = "MosaiqBot/1.0 (+https://mosaiq.example.com/bot)"
URL_TIMEOUT_SECONDS = 10
URL_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def _get_client(shop: Shop, access_token: str) -> ShopifyGraphQLClient:
    from django.conf import settings

    return ShopifyGraphQLClient(shop.domain, access_token, settings.SHOPIFY_API_VERSION)


def run_import_step(job: GenerationJob) -> dict[str, Any]:
    """Execute the import step based on the job's input type.

    Returns a dict with the import result data.
    Sets job status to needs_input for URL-based imports.
    """
    from apps.generator.errors import ImportNotFound
    from apps.generator.import_tasks import import_manual, import_product_gid

    input_data = job.input or {}

    product_gid = input_data.get("product_gid")
    manual = input_data.get("manual")
    source_url = input_data.get("source_url")

    shop = job.shop
    access_token = _get_access_token(shop)

    # Case 1: Existing Shopify product (preferred)
    if product_gid:
        result = import_product_gid(shop, access_token, product_gid)
        return {
            "product_gid": result.product_gid,
            "source_app": result.source_app,
            "title": result.title,
            "facts": result.facts,
            "specs": result.specs,
            "reference_image_urls": result.reference_image_urls,
            "price": str(result.price) if result.price else None,
            "currency": result.currency,
            "locked_fields": result.locked_fields,
        }

    # Case 2: Manual product
    if manual:
        result = import_manual(
            shop,
            access_token,
            title=manual.get("title", ""),
            description=manual.get("description", ""),
            specs=manual.get("specs", {}),
            price=manual.get("price"),
            currency=manual.get("currency"),
        )
        return {
            "product_gid": result.product_gid,
            "source_app": result.source_app,
            "title": result.title,
            "facts": result.facts,
            "specs": result.specs,
            "reference_image_urls": result.reference_image_urls,
            "price": str(result.price) if result.price else None,
            "currency": result.currency,
            "locked_fields": result.locked_fields,
        }

    # Case 3: Source URL — fetch facts, set needs_input
    if source_url:
        return _import_from_url(job, shop, source_url)

    # No valid input
    raise ImportNotFound(message="No product_gid, manual, or source_url in job input")


def _import_from_url(job: GenerationJob, shop: Shop, source_url: str) -> dict[str, Any]:
    """Fetch a URL and extract facts via AI. Sets needs_input for merchant confirmation."""
    from apps.generator.models import JobStatus

    # Fetch the URL
    page_text = _fetch_url(source_url)

    if page_text is None:
        # Blocked or failed — set needs_input with manual form prefilled
        job.status = JobStatus.NEEDS_INPUT
        job.error_code = "IMPORT_SOURCE_BLOCKED"
        job.error_message = "Could not fetch the URL. Please enter product details manually."
        job.save(update_fields=["status", "error_code", "error_message", "updated_at"])

        return {
            "needs_input": True,
            "prefill": {
                "source_url": source_url,
                "title": "",
                "description": "",
                "specs": {},
            },
            "error_code": "IMPORT_SOURCE_BLOCKED",
        }

    # Extract facts via AI (in own words, no verbatim text)
    facts = _extract_url_facts(shop, page_text, source_url)

    # Set needs_input — merchant confirms prefilled form
    job.status = JobStatus.NEEDS_INPUT
    job.save(update_fields=["status", "updated_at"])

    return {
        "needs_input": True,
        "prefill": {
            "source_url": source_url,
            "title": facts.get("title", ""),
            "description": facts.get("description", ""),
            "specs": facts.get("specs", {}),
        },
    }


def _fetch_url(url: str) -> str | None:
    """Fetch a URL with MosaiqBot user agent. Returns page text or None.

    Respects robots.txt, timeout 10s, max 2MB.
    Returns None on 403/404/captcha/timeout/robots.txt block.
    """
    import urllib.robotparser
    from urllib.parse import urlparse

    import httpx

    parsed = urlparse(url)

    # Check robots.txt
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
        if not rp.can_fetch(USER_AGENT, url):
            logger.info("robots.txt disallows %s", url)
            return None
    except Exception:
        # If robots.txt can't be fetched, proceed (conservative would be to block,
        # but most sites don't have robots.txt or it's accessible)
        pass

    try:
        with httpx.Client(
            timeout=URL_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)

            if response.status_code in (403, 404):
                return None

            if response.status_code != 200:
                return None

            # Check content size
            content = response.content
            if len(content) > URL_MAX_BYTES:
                content = content[:URL_MAX_BYTES]

            # Extract text from HTML
            return _extract_text_from_html(content.decode("utf-8", errors="replace"))

    except Exception as e:
        logger.info("Failed to fetch %s: %s", url, e)
        return None


def _extract_text_from_html(html: str) -> str:
    """Extract visible text from HTML. Simple extraction, no external deps."""
    import re

    # Remove script and style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text[:10000]  # Cap at 10k chars for AI processing


def _extract_url_facts(shop: Shop, page_text: str, source_url: str) -> dict[str, Any]:
    """Extract facts from page text via AI. In own words, no verbatim text."""
    from apps.ai.anthropic_client import call_ai
    from apps.ai.schemas import UrlFacts

    try:
        result = call_ai(
            shop=shop,
            purpose="url_facts_extraction",
            model_key="copy",
            system="Extract product facts from the page text. Return title, short description, and key-value specs. Write in your own words — do not copy verbatim text.",
            user=f"Page text:\n{page_text[:8000]}\n\nSource URL: {source_url}",
            schema=UrlFacts,
            tool_name="submit_url_facts",
        )
        facts = result  # type: UrlFacts — fields: title, facts: list[str], specs: dict
        description = "\n\n".join(facts.facts) if facts.facts else ""
        return {
            "title": facts.title,
            "description": description,
            "specs": facts.specs,
        }
    except Exception as e:
        logger.warning("URL facts extraction failed: %s", e)
        return {"title": "", "description": "", "specs": {}}


def _get_access_token(shop: Shop) -> str:
    """Get decrypted access token for a shop."""
    from apps.core.tokens import decrypt_token

    if not shop.access_token_encrypted:
        raise RuntimeError(f"No access token for shop {shop.domain}")

    return decrypt_token(shop.access_token_encrypted)
