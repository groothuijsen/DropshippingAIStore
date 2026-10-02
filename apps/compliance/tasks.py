"""Withdrawal tasks — confirmation email + merchant notification.

See 07 §8.3.3: confirmation email to customer within 1 minute with
content of the declaration and date + time (durable medium).
"""

from __future__ import annotations

import json
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, acks_late=True, max_retries=3)
def send_withdrawal_confirmation(self, request_id: str) -> None:
    """Send confirmation email to the customer with declaration content + date/time."""
    from apps.compliance.models import WithdrawalRequest
    from apps.compliance.withdrawal_labels import get_withdrawal_labels  # noqa: F401

    try:
        request = WithdrawalRequest.objects.get(id=request_id)
    except WithdrawalRequest.DoesNotExist:
        logger.error("WithdrawalRequest %s not found", request_id)
        return

    # Email content: declaration + date + time (durable medium, 07 §8.3.3)
    submitted_str = request.submitted_at.strftime("%Y-%m-%d %H:%M UTC")
    _email_content = f"""
Uw herroepingsverklaring / Your withdrawal declaration

Naam / Name: {request.customer_name}
Bestelling / Order: {request.order_identifier}
Referentie / Reference: {request.reference}
Datum / Date: {submitted_str}

Hiermee bevestigen wij dat wij uw herroepingsverklaring hebben ontvangen.
We confirm that we have received your withdrawal declaration.
"""

    # TODO: Send via email service (Resend/SES) — log for now
    logger.info(
        "Withdrawal confirmation for %s sent to %s",
        request.reference,
        request.email,
    )

    request.confirmation_sent_at = timezone.now()
    request.save(update_fields=["confirmation_sent_at"])


@shared_task(bind=True, acks_late=True, max_retries=3)
def notify_merchant(self, request_id: str) -> None:
    """Notify merchant about a new withdrawal request."""
    from apps.compliance.models import WithdrawalRequest

    try:
        request = WithdrawalRequest.objects.get(id=request_id)
    except WithdrawalRequest.DoesNotExist:
        logger.error("WithdrawalRequest %s not found", request_id)
        return

    # TODO: Send merchant notification email — log for now
    logger.info(
        "Merchant notified: withdrawal %s from %s",
        request.reference,
        request.shop.domain,
    )

    request.merchant_notified_at = timezone.now()
    request.save(update_fields=["merchant_notified_at"])


# ── Delivery metafield sync (F18-4, 12 §4) ─────────────────────────────────


def _get_client(shop):
    """Get a ShopifyGraphQLClient for the shop (decrypts the stored token)."""
    from apps.core.crypto import decrypt_token
    from apps.core.shopify_client import ShopifyGraphQLClient

    token = decrypt_token(shop.access_token_encrypted)
    return ShopifyGraphQLClient(shop.domain, token, "2026-07")


@shared_task(bind=True, acks_late=True, max_retries=3)
def sync_delivery_metafields(self, shop_domain: str) -> None:
    """Write $app:mosaiq.delivery for every product with an estimate (F18-4).

    Batched: max 25 metafields per metafieldsSet call (12 §4). Idempotent —
    the same value is rewritten on every run.
    """
    from apps.compliance.delivery import estimate
    from apps.compliance.models import DeliveryOverride, DeliveryProfile
    from apps.core.models import Shop
    from apps.core.shopify_client import load_query
    from apps.sources.models import ProductSource

    try:
        shop = Shop.objects.get(domain=shop_domain)
    except Shop.DoesNotExist:
        logger.error("Shop %s not found", shop_domain)
        return

    profiled_apps = set(
        DeliveryProfile.objects.filter(shop=shop).values_list("source_app", flat=True)
    )
    override_gids = set(
        DeliveryOverride.objects.filter(shop=shop).values_list("product_gid", flat=True)
    )
    source_gids = set(
        ProductSource.objects.filter(shop=shop, source__in=profiled_apps).values_list(
            "product_gid", flat=True
        )
    )
    affected = source_gids | override_gids
    if not affected:
        logger.info("No delivery-affected products for %s", shop_domain)
        return

    metafields_input = []
    for gid in sorted(affected):
        # Markets in merchant-entered order (profile first, then the
        # product's override) — the first market becomes the metafield
        # default ("the shop's first market", F18-5).
        markets: list[str] = []
        for row in DeliveryProfile.objects.filter(shop=shop):
            for m in (row.transit_days or {}):
                if m not in markets:
                    markets.append(m)
        for row in DeliveryOverride.objects.filter(shop=shop, product_gid=gid):
            for m in (row.transit_days or {}):
                if m not in markets:
                    markets.append(m)
        if not markets:
            continue

        by_market: dict[str, list[int]] = {}
        for market in markets:
            est = estimate(shop, gid, market)
            if est is not None:
                by_market[market] = [est.min_days, est.max_days]
        if not by_market:
            continue

        first_market = markets[0]
        first = by_market[first_market]
        est = estimate(shop, gid, first_market)
        ship_from = est.ship_from if est is not None else ""

        value = {
            "min_days": first[0],
            "max_days": first[1],
            "ship_from": ship_from,
            "by_market": by_market,
            "default_market": first_market,
        }
        metafields_input.append(
            {
                "ownerId": gid,
                "namespace": "$app:mosaiq",
                "key": "delivery",
                "value": json.dumps(value),
            }
        )

    if not metafields_input:
        logger.info("No delivery estimates computable for %s", shop_domain)
        return

    client = _get_client(shop)
    query = load_query("metafields_set")
    try:
        for i in range(0, len(metafields_input), 25):
            batch = metafields_input[i : i + 25]
            data = client.execute(query, {"metafields": batch})
            errors = data.get("metafieldsSet", {}).get("userErrors", [])
            if errors:
                logger.error(
                    "Delivery metafield sync errors for %s: %s", shop_domain, errors
                )
        logger.info(
            "Synced %d delivery metafields for %s", len(metafields_input), shop_domain
        )
    finally:
        client.close()
