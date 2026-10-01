"""Auth flow — token exchange + shop bootstrap on first load.

See docs/03-shopify-integration.md §2.1–2.3.

Flow on a full page load inside the Shopify admin iframe:
1. SessionTokenMiddleware has already validated the session token
   (id_token query param or Authorization: Bearer header).
2. If no Shop exists with a valid token for the request's dest:
   perform token exchange, create/update Shop, queue on_install.
3. Fast path: Shop exists with a valid token → nothing to do.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from django.conf import settings

from .installation import populate_shop_from_info
from .models import Shop
from .shopify_client import ShopifyGraphQLClient, load_query
from .tokens import exchange_token, get_access_token, store_tokens

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _extract_session_token(request: HttpRequest) -> str | None:
    """Extract the session token the same way the middleware does."""
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.GET.get("id_token")


def ensure_shop(request: HttpRequest) -> Shop | None:
    """Ensure a Shop exists with valid tokens for this request.

    Returns the Shop, or None if it could not be established
    (no shop domain on the request, or token exchange failed).
    """
    shop_domain: str | None = getattr(request, "shop_domain", None)
    if not shop_domain:
        return None

    # Fast path — shop exists with a usable token
    shop = Shop.objects.filter(domain=shop_domain).first()
    if shop and not shop.needs_reauth and get_access_token(shop):
        return shop

    # Slow path — token exchange
    session_token = _extract_session_token(request)
    if not session_token:
        logger.warning("No session token available for %s", shop_domain)
        return shop  # may be None

    from .tasks import run_on_install

    try:
        token_data = asyncio.run(exchange_token(session_token, shop_domain))
    except Exception as exc:
        logger.error("Token exchange failed for %s: %s", shop_domain, exc)
        return shop

    access_token = token_data["access_token"]

    # Fetch shop info to populate the Shop record
    try:
        client = ShopifyGraphQLClient(shop_domain, access_token, settings.SHOPIFY_API_VERSION)
        try:
            data = client.execute(load_query("shop_info"))
        finally:
            client.close()
        shop = populate_shop_from_info(data, domain=shop_domain)
    except Exception as exc:
        logger.error("shop_info failed for %s: %s", shop_domain, exc)
        return None

    store_tokens(shop, token_data)

    # Start installation tasks (idempotent, runs in Celery)
    run_on_install.delay(str(shop.id))

    logger.info("Shop %s bootstrapped via token exchange", shop_domain)
    return shop
