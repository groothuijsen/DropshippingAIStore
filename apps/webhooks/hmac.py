"""HMAC validation for Shopify webhooks.

See docs/03-shopify-integration.md §3.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from django.conf import settings


def validate_shopify_hmac(raw_body: bytes, hmac_header: str) -> bool:
    """Validate the X-Shopify-Hmac-Sha256 header against the raw request body.

    Returns True if the HMAC is valid, False otherwise.
    """
    if not hmac_header:
        return False

    secret = settings.SHOPIFY_API_SECRET.encode("utf-8")
    digest = hashlib.sha256(secret + raw_body).digest()
    expected = base64.b64encode(digest).decode("utf-8")

    return hmac.compare_digest(expected, hmac_header)
