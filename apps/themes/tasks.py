"""Celery tasks for themes — design-token sync (F05-5, F15-5)."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(acks_late=True, max_retries=2)
def sync_brand_tokens(shop_id: str) -> None:
    """Write design_tokens to the app installation metafield for a shop."""
    from apps.core.crypto import decrypt_token
    from apps.core.models import Shop
    from apps.themes.models import BrandKit
    from apps.themes.tokens import sync_tokens_to_metafield

    try:
        shop = Shop.objects.get(id=shop_id)
    except Shop.DoesNotExist:
        logger.warning("sync_brand_tokens: shop %s not found", shop_id)
        return
    brandkit = BrandKit.objects.filter(shop=shop).first()
    if brandkit is None:
        logger.warning("sync_brand_tokens: no BrandKit for shop %s", shop.domain)
        return
    token = decrypt_token(shop.access_token_encrypted)
    ok = sync_tokens_to_metafield(shop, token, brandkit)
    logger.info("sync_brand_tokens: %s -> %s", shop.domain, ok)
