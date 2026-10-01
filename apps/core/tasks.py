"""Core Celery tasks."""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import models, transaction
from django.utils import timezone

from .models import Shop, ShopStatus
from .tokens import refresh_access_token

logger = logging.getLogger(__name__)


@shared_task(name="core.tasks.keep_tokens_fresh")
def keep_tokens_fresh() -> dict[str, int]:
    """Refresh tokens of active shops whose ACCESS or REFRESH token expires soon.

    Runs hourly via Celery beat. The access token window is the critical one:
    Shopify offline access tokens rotate, and any task that runs after expiry
    fails with 401 (dev store loop, 2026-10-01). The 14-day refresh-token
    window is kept as a second safety net.
    """
    from datetime import timedelta

    access_cutoff = timezone.now() + timedelta(hours=1)
    refresh_cutoff = timezone.now() + timedelta(days=14)
    shops = Shop.objects.filter(
        status=ShopStatus.ACTIVE,
        needs_reauth=False,
    ).filter(
        models.Q(access_token_expires_at__lte=access_cutoff)
        | models.Q(refresh_token_expires_at__lte=refresh_cutoff)
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


@shared_task(name="core.tasks.run_on_install")
def run_on_install(shop_id: str) -> dict[str, str]:
    """Celery task wrapper for on_install.

    Fetches the shop, decrypts the access token, and runs the installation flow.
    """
    from .crypto import decrypt_token
    from .installation import on_install

    try:
        shop = Shop.objects.get(id=shop_id)
    except Shop.DoesNotExist:
        logger.error("Shop %s not found for on_install", shop_id)
        return {"error": "shop_not_found"}

    try:
        access_token = decrypt_token(shop.access_token_encrypted)
    except Exception:
        logger.error("Cannot decrypt access token for %s", shop.domain)
        return {"error": "token_decrypt_failed"}

    try:
        on_install(shop.domain, access_token)
        return {"status": "completed", "shop": shop.domain}
    except Exception as exc:
        logger.error("Installation failed for %s: %s", shop.domain, exc)
        return {"error": str(exc)}
