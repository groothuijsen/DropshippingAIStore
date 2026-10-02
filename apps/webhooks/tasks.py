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
    "products/create": "handle_product_create",
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
    """Set Shop.status = uninstalled, cancel running jobs, wipe tokens.

    See docs/specs/F13-uninstall-gdpr.md criterion 1.
    """
    from apps.core.models import AuditLog, Shop, ShopStatus

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

    # Cancel running jobs (F13 criterion 1)
    from apps.generator.models import GenerationJob, JobStatus

    running = GenerationJob.objects.filter(
        shop=shop,
        status__in=[JobStatus.RUNNING, JobStatus.QUEUED],
    )
    cancelled = running.update(status=JobStatus.CANCELLED)

    # Audit log event
    AuditLog.objects.create(
        shop=shop,
        actor="system",
        action="uninstalled",
        payload={"cancelled_jobs": cancelled},
    )

    logger.info(
        "Shop %s uninstalled, %d jobs cancelled",
        receipt.shop_domain,
        cancelled,
    )


def handle_subscription_update(receipt: WebhookReceipt) -> None:
    """Update Subscription.status from the payload."""
    # TODO: Implement in T-060 (billing)
    logger.info("Subscription update webhook for %s — TODO", receipt.shop_domain)


def _snapshot_variant_prices(shop, body: dict | None) -> int:
    """Record variant prices into PriceHistory if they differ from the last row.

    Shared by products/create and products/update handlers. Idempotent:
    an unchanged price never creates a second row (AGENTS.md §3).
    Returns the number of rows created.
    """
    from decimal import Decimal, InvalidOperation

    from apps.compliance.models import PriceHistory

    if body is None:
        logger.warning("No body parsed — skipping price snapshot for shop %s", shop.domain)
        return 0

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

    return created


def handle_product_create(receipt: WebhookReceipt) -> None:
    """New product: snapshot its initial variant prices into PriceHistory."""
    from apps.core.models import Shop

    shop = Shop.objects.filter(domain=receipt.shop_domain).first()
    if not shop:
        logger.warning("Shop %s not found for products/create webhook", receipt.shop_domain)
        return

    created = _snapshot_variant_prices(shop, receipt.body_json)
    _record_imported_product(shop, receipt.body_json)
    logger.info(
        "Product create for %s: %d initial price rows created",
        receipt.shop_domain,
        created,
    )


def _record_imported_product(shop, body: dict | None) -> None:
    """Append the product to the wizard's imported_products (F15-7).

    Fast signal for the import-waiting screen; the screen also runs a
    fallback products query. Idempotent by product GID.
    """
    from apps.generator.models import BlueprintStatus, StoreBlueprint

    if not body:
        return
    gid = str(body.get("id") or "")
    if not gid:
        return
    # Webhooks deliver plain numeric IDs, the Admin API returns GIDs —
    # normalize so the import screen merges and selects consistently.
    if gid.isdigit():
        gid = f"gid://shopify/Product/{gid}"
    bp = (
        StoreBlueprint.objects.filter(shop=shop)
        .order_by("-created_at")
        .first()
    )
    if bp is None or bp.started_products_at is None:
        return
    if bp.status not in (BlueprintStatus.IDEAS, BlueprintStatus.STRUCTURE):
        return
    items = list(bp.imported_products or [])
    if any(item.get("gid") == gid for item in items):
        return
    items.append(
        {
            "gid": gid,
            "title": body.get("title") or "",
            "vendor": body.get("vendor") or "",
            "created_at": body.get("created_at") or "",
        }
    )
    bp.imported_products = items
    bp.save(update_fields=["imported_products", "updated_at"])


def handle_product_update(receipt: WebhookReceipt) -> None:
    """New prices per variant into PriceHistory if they differ from the last row."""
    from apps.core.models import Shop

    shop = Shop.objects.filter(domain=receipt.shop_domain).first()
    if not shop:
        logger.warning("Shop %s not found for products/update webhook", receipt.shop_domain)
        return

    body = receipt.body_json if hasattr(receipt, "body_json") else None
    if body is None:
        logger.warning("No body parsed for webhook %s — skipping price snapshot", receipt.webhook_id)
        return

    created = _snapshot_variant_prices(shop, body)
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


def handle_customer_redact(receipt: WebhookReceipt) -> None:
    """Delete WithdrawalRequest rows with the email address from the payload.

    See docs/specs/F11-compliance.md criterion 20.
    """
    from apps.compliance.models import WithdrawalRequest

    body = receipt.body_json or {}
    email = body.get("email", "")
    if not email:
        logger.warning("customers/redact without email for %s", receipt.shop_domain)
        return

    deleted = WithdrawalRequest.objects.filter(email=email).delete()
    logger.info(
        "Customer redact for %s: %d withdrawal requests deleted",
        receipt.shop_domain,
        deleted[0],
    )


def handle_customer_data_request(receipt: WebhookReceipt) -> None:
    """Export WithdrawalRequest rows with the email address from the payload.

    See docs/specs/F11-compliance.md criterion 20.
    """
    from apps.compliance.models import WithdrawalRequest

    body = receipt.body_json or {}
    email = body.get("email", "")
    if not email:
        logger.warning("customers/data_request without email for %s", receipt.shop_domain)
        return

    requests = WithdrawalRequest.objects.filter(email=email)
    export_data = [
        {
            "reference": r.reference,
            "customer_name": r.customer_name,
            "order_identifier": r.order_identifier,
            "email": r.email,
            "locale": r.locale,
            "submitted_at": r.submitted_at.isoformat(),
            "status": r.status,
        }
        for r in requests
    ]
    logger.info(
        "Customer data request for %s: %d withdrawal requests exported",
        receipt.shop_domain,
        len(export_data),
    )
    # TODO: Send export to merchant via email/API


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
