"""Shopify webhook endpoints.

See docs/03-shopify-integration.md §3.
"""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .hmac import validate_shopify_hmac
from .models import WebhookReceipt

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def shopify_webhook(request: HttpRequest) -> JsonResponse:
    """Handle inbound Shopify webhooks.

    1. Validate HMAC.
    2. Deduplicate on X-Shopify-Webhook-Id.
    3. Dispatch to Celery task.
    4. Return 200 within 5 seconds.
    """
    # Validate HMAC
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    raw_body = request.body

    if not validate_shopify_hmac(raw_body, hmac_header):
        logger.warning("Invalid HMAC from %s", request.META.get("REMOTE_ADDR", "unknown"))
        return JsonResponse({"error": "invalid_hmac"}, status=401)

    # Extract headers
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
    topic = request.headers.get("X-Shopify-Topic", "")
    shop_domain = request.headers.get("X-Shopify-Hmac-Sha256", "")  # Will be set by middleware

    # Try to get shop_domain from the topic header or body
    # The actual shop domain comes from the session token middleware
    # For webhooks, we need to extract it differently
    if not shop_domain:
        # Try to extract from the body
        try:
            body = json.loads(raw_body)
            # Some webhooks include shop_domain in the body
            shop_domain = body.get("shop_domain", body.get("shop", {}).get("domain", ""))
        except (json.JSONDecodeError, AttributeError):
            pass

    # Deduplicate
    receipt, created = WebhookReceipt.objects.get_or_create(
        webhook_id=webhook_id,
        defaults={
            "topic": topic,
            "shop_domain": shop_domain,
        },
    )

    if not created:
        # Already processed — return 200 immediately
        logger.info("Duplicate webhook %s — skipping", webhook_id)
        return JsonResponse({"status": "ok"})

    # Dispatch to Celery task
    from .tasks import process_webhook

    process_webhook.delay(receipt.id)

    return JsonResponse({"status": "ok"})
