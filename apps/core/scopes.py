"""Scope checks for the F15 "Start from zero" route (12 §4, T-110).

Existing installs must re-authorise to grant the new scopes
`write_online_store_navigation` + `write_publications`. Until granted, the
wizard shows an explanation and a button to grant them; no build can start
(`GeneratorError` code ``SCOPE_MISSING``).

Granted scopes are read live via ``currentAppInstallation { accessScopes }``
(queries/current_installation_scopes.graphql) — never inferred from the
token, because Shopify keeps old tokens valid without the new scopes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings

from .shopify_client import ShopifyGraphQLClient, load_query

if TYPE_CHECKING:
    from .models import Shop

logger = logging.getLogger(__name__)

#: Scopes the "Start from zero" route needs on top of the base install set.
#: `read_publications` is required by the publications QUERY (live-verified
#: access denial on the dev store — write_publications does not cover it).
REQUIRED_START_SCOPES: tuple[str, ...] = (
    "write_online_store_navigation",
    "read_publications",
    "write_publications",
)


def _get_client(shop_domain: str, access_token: str) -> ShopifyGraphQLClient:
    return ShopifyGraphQLClient(shop_domain, access_token, settings.SHOPIFY_API_VERSION)


def get_granted_scopes(shop_domain: str, access_token: str) -> set[str]:
    """Return the set of scope handles currently granted on the shop.

    Raises on GraphQL/userErrors — callers treat any failure as
    "scopes unknown" and block the build (safe default).
    """
    client = _get_client(shop_domain, access_token)
    try:
        result = client.execute(load_query("current_installation_scopes"))
    finally:
        client.close()

    # API 2026-07: accessScopes is a plain LIST of {handle}, not a
    # connection with nodes (live-verified on the dev store 2026-10-01).
    access_scopes = result["currentAppInstallation"]["accessScopes"]
    if isinstance(access_scopes, dict):
        access_scopes = access_scopes.get("nodes", [])
    return {node["handle"] for node in access_scopes}


def missing_scopes(granted: set[str]) -> list[str]:
    """Return the REQUIRED_START_SCOPES not present in `granted`."""
    return [scope for scope in REQUIRED_START_SCOPES if scope not in granted]


def build_regrant_url(shop_domain: str) -> str:
    """OAuth authorize URL that requests the full scope set again.

    Redirecting an already-installed shop here makes Shopify show the
    re-authorisation screen for the additional scopes (12 §4).
    """
    scope_csv = ",".join(
        [
            "write_products",
            "write_discounts",
            "write_online_store_pages",
            "write_files",
            "read_inventory",
            "read_locales",
            "read_markets",
            *REQUIRED_START_SCOPES,
        ]
    )
    redirect_uri = f"{settings.APP_URL.rstrip('/')}/auth/callback"
    from urllib.parse import quote

    return (
        f"https://{shop_domain}/admin/oauth/authorize"
        f"?client_id={settings.SHOPIFY_API_KEY}"
        f"&scope={quote(scope_csv, safe=',')}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
    )


def check_start_scopes(shop: Shop) -> dict[str, Any]:
    """Full check used by the wizard before a build can start.

    Returns a dict with:
      - ``ok``: True when all required scopes are granted
      - ``missing``: list of missing scope handles
      - ``regrant_url``: URL for the re-grant button (always present)
      - ``error``: "SCOPE_MISSING" when not ok, else None
    """
    from .crypto import decrypt_token

    regrant_url = build_regrant_url(shop.domain)
    try:
        granted = get_granted_scopes(shop.domain, decrypt_token(shop.access_token_encrypted))
    except Exception as exc:
        # Cannot verify → safe default is to block the build.
        logger.warning("Scope check failed for %s: %s", shop.domain, exc)
        return {
            "ok": False,
            "missing": list(REQUIRED_START_SCOPES),
            "regrant_url": regrant_url,
            "error": "SCOPE_MISSING",
        }

    missing = missing_scopes(granted)
    return {
        "ok": not missing,
        "missing": missing,
        "regrant_url": regrant_url,
        "error": "SCOPE_MISSING" if missing else None,
    }
