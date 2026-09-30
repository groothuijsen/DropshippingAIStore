"""Celery tasks for billing — reconcile, trial warning.

See docs/08-billing.md §4–5.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, acks_late=True, max_retries=3)
def reconcile(self, shop_id: str) -> dict[str, Any]:
    """Daily beat task: compare Subscription.status with currentAppInstallation.

    See 08 §5. Active shops only, token valid.
    """
    from apps.core.models import Shop, ShopStatus
    from apps.core.shopify_client import ShopifyGraphQLClient, load_query
    from apps.core.tokens import decrypt_token

    from .models import Subscription

    try:
        shop = Shop.objects.get(id=shop_id)
    except Shop.DoesNotExist:
        return {"error": "shop_not_found"}

    if shop.status != ShopStatus.ACTIVE:
        return {"skipped": "shop_not_active"}

    if not shop.access_token_encrypted:
        return {"skipped": "no_access_token"}

    access_token = decrypt_token(shop.access_token_encrypted)

    client = ShopifyGraphQLClient(shop.domain, access_token, settings_shoapi())
    try:
        query = load_query("current_installation")
        data = client.execute(query, {})
    finally:
        client.close()

    active_subs = data.get("currentAppInstallation", {}).get("activeSubscriptions", [])

    sub = Subscription.objects.filter(shop=shop).first()

    if not active_subs:
        # No active subscriptions on Shopify
        if sub and sub.status == "active":
            sub.status = "cancelled"
            sub.save(update_fields=["status", "updated_at"])
            logger.info("Reconcile: %s subscription cancelled on Shopify", shop.domain)
            return {"updated": "cancelled", "shop": shop.domain}
        return {"status": "no_change"}

    # Has active subscription
    shopify_sub = active_subs[0]
    shopify_status = shopify_sub.get("status", "").lower()
    shopify_gid = shopify_sub.get("id", "")

    if sub is None:
        # Create subscription record
        sub = Subscription.objects.create(
            shop=shop,
            plan="starter",  # Default, will be updated
            shopify_subscription_gid=shopify_gid,
            status=shopify_status,
            trial_ends_at=shopify_sub.get("trialDays"),
            current_period_end=shopify_sub.get("currentPeriodEnd"),
            test=shopify_sub.get("test", False),
        )
        logger.info("Reconcile: created subscription for %s", shop.domain)
        return {"created": True, "shop": shop.domain}

    # Update if status changed
    if sub.status != shopify_status:
        old_status = sub.status
        sub.status = shopify_status
        sub.shopify_subscription_gid = shopify_gid
        sub.save(update_fields=["status", "shopify_subscription_gid", "updated_at"])
        logger.info(
            "Reconcile: %s status %s → %s",
            shop.domain,
            old_status,
            shopify_status,
        )
        return {"updated": shopify_status, "shop": shop.domain}

    return {"status": "no_change"}


def settings_shoapi() -> str:
    """Get Shopify API version from settings."""
    from django.conf import settings

    return settings.SHOPIFY_API_VERSION


@shared_task(bind=True, acks_late=True, max_retries=3)
def check_trial_expiring(self) -> dict[str, Any]:
    """Hourly beat: find trials ending within 48h, send warning.

    See 08 §4.
    """
    from .models import Subscription

    now = timezone.now()
    threshold = now + timedelta(hours=48)

    expiring = Subscription.objects.filter(
        status="active",
        trial_ends_at__lte=threshold,
        trial_ends_at__gt=now,
    ).select_related("shop")

    count = 0
    for sub in expiring:
        # TODO: Send email via email service (T-061)
        logger.info(
            "Trial expiring: %s ends %s",
            sub.shop.domain,
            sub.trial_ends_at,
        )
        count += 1

    return {"checked": True, "expiring_soon": count}


def get_trial_days_for_domain(domain: str) -> int:
    """Get trial days for a domain. 7 if new, 0 if already had a trial.

    See 08 §4, F12 criterion 4.
    """
    from .models import TrialLedger
    from .plans import TRIAL_DAYS

    domain_hash = hashlib.sha256(domain.lower().encode()).hexdigest()

    if TrialLedger.objects.filter(domain_sha256=domain_hash).exists():
        return 0

    return TRIAL_DAYS


def record_trial_started(domain: str) -> None:
    """Record that a trial started for this domain."""
    from .models import TrialLedger

    domain_hash = hashlib.sha256(domain.lower().encode()).hexdigest()
    TrialLedger.objects.get_or_create(
        domain_sha256=domain_hash,
        defaults={"first_trial_at": timezone.now()},
    )
