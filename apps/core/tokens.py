"""Token exchange and refresh for Shopify offline access tokens.

See docs/03-shopify-integration.md §2.3–2.3a.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
import redis
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .crypto import decrypt_token, encrypt_token

if TYPE_CHECKING:
    from .models import Shop

logger = logging.getLogger(__name__)

TOKEN_REFRESH_LOCK_PREFIX = "mq:token-refresh:"
TOKEN_REFRESH_LOCK_TIMEOUT = 30  # seconds


def _get_redis() -> redis.Redis:
    """Return a Redis connection for locking."""
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


async def exchange_token(session_token: str, shop_domain: str) -> dict:
    """Exchange a Shopify session token for an offline access token.

    Returns the raw token response dict with access_token, refresh_token, etc.
    """
    url = f"https://{shop_domain}/admin/oauth/access_token"
    payload = {
        "client_id": settings.SHOPIFY_API_KEY,
        "client_secret": settings.SHOPIFY_API_SECRET,
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": session_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
        "requested_token_type": "urn:shopify:params:oauth:token-type:offline-access-token",
        "expiring": 1,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def store_tokens(shop: Shop, token_data: dict, *, is_refresh: bool = False) -> None:
    """Encrypt and store tokens from a token exchange or refresh response.

    In a single DB transaction.
    """
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    expires_in = token_data.get("expires_in", 3600)
    refresh_expires_in = token_data.get("refresh_token_expires_in", 7_776_000)
    scope = token_data.get("scope", "")

    now = timezone.now()

    with transaction.atomic():
        shop.access_token_encrypted = encrypt_token(access_token)
        shop.access_token_expires_at = now + timedelta(seconds=expires_in)
        shop.refresh_token_encrypted = encrypt_token(refresh_token)
        shop.refresh_token_expires_at = now + timedelta(seconds=refresh_expires_in)
        shop.scopes = scope
        shop.needs_reauth = False
        shop.save(
            update_fields=[
                "access_token_encrypted",
                "access_token_expires_at",
                "refresh_token_encrypted",
                "refresh_token_expires_at",
                "scopes",
                "needs_reauth",
            ]
        )


def refresh_access_token(shop: Shop) -> bool:
    """Refresh the access token using the stored refresh token.

    Returns True on success, False on failure (sets needs_reauth).
    """
    try:
        refresh_token = decrypt_token(shop.refresh_token_encrypted)
    except Exception:
        logger.error("Cannot decrypt refresh token for %s", shop.domain)
        shop.needs_reauth = True
        shop.save(update_fields=["needs_reauth"])
        return False

    url = f"https://{shop.domain}/admin/oauth/access_token"
    payload = {
        "client_id": settings.SHOPIFY_API_KEY,
        "client_secret": settings.SHOPIFY_API_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=10)
        if resp.status_code in (400, 401):
            logger.warning("Token refresh failed for %s: %s", shop.domain, resp.status_code)
            shop.needs_reauth = True
            shop.save(update_fields=["needs_reauth"])
            return False
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Token refresh HTTP error for %s: %s", shop.domain, exc)
        shop.needs_reauth = True
        shop.save(update_fields=["needs_reauth"])
        return False

    store_tokens(shop, resp.json(), is_refresh=True)
    return True


def get_access_token(shop: Shop) -> str | None:
    """Get a valid access token for the shop.

    1. Return current token if valid for > 5 minutes.
    2. Otherwise, acquire Redis lock and refresh.
    3. Two concurrent calls for the same shop refresh only once.

    Returns the decrypted access token or None if needs_reauth.
    """
    if shop.needs_reauth:
        return None

    # Check if current token is still valid
    now = timezone.now()
    if shop.access_token_expires_at and (shop.access_token_expires_at - now) > timedelta(minutes=5):
        try:
            return decrypt_token(shop.access_token_encrypted)
        except Exception:
            logger.error("Cannot decrypt access token for %s", shop.domain)
            return None

    # Need to refresh — use Redis lock
    lock_key = f"{TOKEN_REFRESH_LOCK_PREFIX}{shop.id}"
    r = _get_redis()

    try:
        locked = r.set(lock_key, "1", nx=True, ex=TOKEN_REFRESH_LOCK_TIMEOUT)
    except redis.RedisError:
        logger.warning("Could not acquire refresh lock for %s", shop.domain)
        return None

    if not locked:
        logger.warning("Could not acquire refresh lock for %s", shop.domain)
        return None

    try:
        # Re-read shop inside the lock (another worker may have just refreshed)
        shop.refresh_from_db()
        now = timezone.now()
        if shop.access_token_expires_at and (shop.access_token_expires_at - now) > timedelta(minutes=5):
            try:
                return decrypt_token(shop.access_token_encrypted)
            except Exception:
                return None

        success = refresh_access_token(shop)
        if success:
            try:
                return decrypt_token(shop.access_token_encrypted)
            except Exception:
                return None
        return None
    finally:
        r.delete(lock_key)
