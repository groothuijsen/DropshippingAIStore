"""Webhook processing tasks.

See docs/03-shopify-integration.md §3.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .models import WebhookReceipt

logger = logging.getLogger(__name__)

# Topic → action mapping
WEBHOOK_HANDLERS: dict[str, str] = {
    "app/uninstalled": "handle_app_uninstalled",
    "app_subscriptions/update": "handle_subscription_update",
    "products/update": "handle_product_update",
    "products/delete": "handle_product_delete",
    "shop/update": "handle_shop_update",
    "customers/data_request": "handle_customer_data_request",
    "customers/redact": "handle_customer_redact",
    "shop/redact": "handle_shop_redact",
}


@shared_task(bind=True, acks_late=True, max_retries=3)
def process_webhook(self, receipt_id: int) -> None:
    """Process an inbound webhook by dispatching to the appropriate handler."""
    try:
        receipt = WebhookReceipt.objects.get(id=receipt_id)
    except WebhookReceipt.DoesNotExist:
        logger.error("WebhookReceipt %d not found", receipt_id)
        return

    if receipt.processed:
        logger.info("Webhook %s already processed — skipping", receipt.webhook_id)
        return

    topic = receipt.topic
    handler_name = WEBHOOK_HANDLERS.get(topic)

    if not handler_name:
        logger.warning("No handler for webhook topic: %s", topic)
        receipt.processed = True
        receipt.save(update_fields=["processed"])
        return

    try:
        # Import the handler dynamically
        handler = globals()[handler_name]
        handler(receipt)
    except Exception as exc:
        logger.error("Webhook handler failed for %s: %s", topic, exc)
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc

    receipt.processed = True
    receipt.save(update_fields=["processed"])
    logger.info("Webhook %s processed successfully", receipt.webhook_id)


def handle_app_uninstalled(receipt: WebhookReceipt) -> None:
    """Set Shop.status = uninstalled, wipe tokens."""
    from apps.core.models import Shop, ShopStatus

    shop = Shop.objects.filter(domain=receipt.shop_domain).first()
    if not shop:
        logger.warning("Shop %s not found for uninstall webhook", receipt.shop_domain)
        return

    shop.status = ShopStatus.UNINSTALLED
    shop.uninstalled_at = timezone.now()
    shop.access_token_encrypted = b""
    shop.refresh_token_encrypted = b""
    shop.save(
        update_fields=[
            "status",
            "uninstalled_at",
            "access_token_encrypted",
            "refresh_token_encrypted",
        ]
    )
    logger.info("Shop %s uninstalled", receipt.shop_domain)


def handle_subscription_update(receipt: WebhookReceipt) -> None:
    """Update Subscription.status from the payload."""
    # TODO: Implement in T-060 (billing)
    logger.info("Subscription update webhook for %s — TODO", receipt.shop_domain)


def handle_product_update(receipt: WebhookReceipt) -> None:
    """New prices per variant into PriceHistory if they differ from the last row."""
    import json
    from decimal import Decimal, InvalidOperation

    from apps.compliance.models import PriceHistory
    from apps.core.crypto import decrypt_token
    from apps.core.models import Shop

    shop = Shop.objects.filter(domain=receipt.shop_domain).first()
    if not shop:
        logger.warning("Shop %s not found for products/update webhook", receipt.shop_domain)
        return

    # Parse the webhook body
    body = receipt.body_json if hasattr(receipt, "body_json") else None
    if body is None:
        # Re-read from stored raw body if available
        logger.warning("No body parsed for webhook %s — skipping price snapshot", receipt.webhook_id)
        return

    variants = body.get("variants", [])
    now = timezone.now()
    created = 0

    for variant in variants:
        variant_gid = variant.get("admin_graphql_api_id", "")
        price_str = variant.get("price", "0")
        currency = shop.currency_code

        if not variant_gid:
            continue

        try:
            price = Decimal(price_str)
        except (InvalidOperation, TypeError):
            continue

        last = (
            PriceHistory.objects.filter(
                shop=shop,
                variant_gid=variant_gid,
                market_handle="primary",
            )
            .order_by("-observed_at")
            .first()
        )

        if last and last.price == price:
            continue  # Same price, no new row

        PriceHistory.objects.create(
            shop=shop,
            variant_gid=variant_gid,
            market_handle="primary",
            price=price,
            currency=currency,
            observed_at=now,
            source="webhook",
        )
        created += 1

    logger.info("Product update for %s: %d price rows created", receipt.shop_domain, created)


def handle_product_delete(receipt: WebhookReceipt) -> None:
    """Linked Page rows → archived; delete metaobject."""
    # TODO: Implement in T-050 (pages)
    logger.info("Product delete webhook for %s — TODO", receipt.shop_domain)


def handle_shop_update(receipt: WebhookReceipt) -> None:
    """Update name, email, currency_code, iana_timezone."""
    from apps.core.models import Shop

    shop = Shop.objects.filter(domain=receipt.shop_domain).first()
    if not shop:
        logger.warning("Shop %s not found for shop/update webhook", receipt.shop_domain)
        return

    # Parse the body — we need to re-read it since we don't store it
    # For now, log and skip — actual implementation will parse the body
    logger.info("Shop update webhook for %s — TODO", receipt.shop_domain)


def handle_customer_data_request(receipt: WebhookReceipt) -> None:
    """Export WithdrawalRequest rows with the email address from the payload."""
    # TODO: Implement in T-088 (withdrawal form)
    logger.info("Customer data request for %s — TODO", receipt.shop_domain)


def handle_customer_redact(receipt: WebhookReceipt) -> None:
    """Delete WithdrawalRequest rows with the email address from the payload."""
    # TODO: Implement in T-088 (withdrawal form)
    logger.info("Customer redact for %s — TODO", receipt.shop_domain)


def handle_shop_redact(receipt: WebhookReceipt) -> None:
    """Delete Shop (CASCADE). Ignore if shop has since been reinstalled."""
    from apps.core.models import Shop, ShopStatus

    shop = Shop.objects.filter(domain=receipt.shop_domain).first()
    if not shop:
        logger.info("Shop %s already deleted — ignoring shop/redact", receipt.shop_domain)
        return

    # Ignore if shop has been reinstalled
    if (
        shop.status == ShopStatus.ACTIVE
        and shop.installed_at
        and shop.uninstalled_at
        and shop.installed_at > shop.uninstalled_at
    ):
        logger.info("Shop %s reinstalled — ignoring shop/redact", receipt.shop_domain)
        return

    shop.delete()
    logger.info("Shop %s deleted via shop/redact", receipt.shop_domain)
