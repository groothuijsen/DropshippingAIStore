"""Core Celery tasks."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Shop, ShopStatus
from .tokens import refresh_access_token

logger = logging.getLogger(__name__)


@shared_task(name="core.tasks.keep_tokens_fresh")
def keep_tokens_fresh() -> dict[str, int]:
    """Refresh tokens of active shops whose refresh_token expires within 14 days.

    Runs daily via Celery beat. Prevents quiet stores from losing their token.
    """
    from datetime import timedelta

    cutoff = timezone.now() + timedelta(days=14)
    shops = Shop.objects.filter(
        status=ShopStatus.ACTIVE,
        needs_reauth=False,
        refresh_token_expires_at__lte=cutoff,
    ).select_for_update(skip_locked=True)

    refreshed = 0
    failed = 0

    with transaction.atomic():
        for shop in shops:
            try:
                if refresh_access_token(shop):
                    refreshed += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error("Token refresh failed for %s: %s", shop.domain, exc)
                failed += 1

    return {"refreshed": refreshed, "failed": failed}
