"""App proxy signature validation — HMAC-SHA256 per 03 §1.

Validate every proxy request on the `signature` query parameter:
HMAC-SHA256 of the sorted query, without `signature`, with SHOPIFY_API_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode


def validate_proxy_signature(query_params: dict[str, str], api_secret: str) -> bool:
    """Validate the Shopify app proxy signature.

    HMAC-SHA256 of the sorted query string (without `signature`), keyed with api_secret.
    Returns True if valid.
    """
    signature = query_params.get("signature", "")
    if not signature:
        return False

    # Build the message: sorted query params without `signature`
    params = {k: v for k, v in query_params.items() if k != "signature"}
    sorted_query = urlencode(sorted(params.items()))

    expected = hmac.new(
        api_secret.encode("utf-8"),
        sorted_query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected)
