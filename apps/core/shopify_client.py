"""GraphQL client for the Shopify Admin API.

See docs/03-shopify-integration.md §4–5.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────


class ShopifyGraphQLError(Exception):
    """Top-level GraphQL errors (not userErrors)."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        msg = "; ".join(e.get("message", str(e)) for e in errors)
        super().__init__(msg)


class ShopifyUserError(Exception):
    """Non-empty userErrors in a mutation response."""

    def __init__(self, field: str, message: str, code: str | None = None):
        self.field = field
        self.message = message
        self.code = code
        super().__init__(f"{field}: {message} (code={code})")


class ShopifyThrottledError(Exception):
    """Shopify returned THROTTLED after exhausting retries."""


class ShopifyAuthError(Exception):
    """HTTP 401/403 — token invalid."""

    pass


# ── .graphql loader ───────────────────────────────────────────────────────

_QUERIES_DIR = Path(__file__).resolve().parent.parent.parent / "queries"


def load_query(name: str) -> str:
    """Load a .graphql file from the queries/ directory."""
    path = _QUERIES_DIR / f"{name}.graphql"
    if not path.exists():
        raise FileNotFoundError(f"GraphQL query not found: {path}")
    return path.read_text().strip()


# ── Client ────────────────────────────────────────────────────────────────

MAX_THROTTLE_RETRIES = 5
THROTTLE_BACKOFFS = [1, 2, 4, 8, 16]


class ShopifyGraphQLClient:
    """Synchronous GraphQL client with throttling and error handling."""

    def __init__(self, shop_domain: str, access_token: str, api_version: str):
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.api_version = api_version
        self.endpoint = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout=30.0, connect=5.0),
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query/mutation and return the data dict.

        Handles throttling, top-level errors, and userErrors.
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        last_exc: Exception | None = None

        for attempt in range(MAX_THROTTLE_RETRIES):
            try:
                resp = self._client.post(self.endpoint, json=payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    raise ShopifyAuthError(f"Auth failed ({exc.response.status_code}) for {self.shop_domain}") from exc
                raise

            # HTTP-level auth errors
            if resp.status_code in (401, 403):
                raise ShopifyAuthError(f"Auth failed ({resp.status_code}) for {self.shop_domain}")

            body = resp.json()

            # Top-level errors
            if "errors" in body and body["errors"]:
                errors = body["errors"]
                # Check for throttling
                if any(e.get("extensions", {}).get("code") == "THROTTLED" for e in errors):
                    backoff = THROTTLE_BACKOFFS[min(attempt, len(THROTTLE_BACKOFFS) - 1)]
                    logger.warning("Throttled on %s, backing off %ds", self.shop_domain, backoff)
                    time.sleep(backoff)
                    last_exc = ShopifyThrottledError(f"Throttled after {attempt + 1} retries")
                    continue
                raise ShopifyGraphQLError(errors)

            # Throttle status — proactive wait
            cost_info = body.get("extensions", {}).get("cost", {}).get("throttleStatus", {})
            if cost_info:
                available = cost_info.get("currentlyAvailable", 0)
                restore_rate = cost_info.get("restoreRate", 1)
                requested = body.get("extensions", {}).get("cost", {}).get("requestedQueryCost", 0)
                if requested and requested > available:
                    wait = (requested - available) / restore_rate
                    logger.info("Proactive throttle wait %.1fs on %s", wait, self.shop_domain)
                    time.sleep(wait)

            # userErrors
            data = body.get("data", {})
            for _key, value in data.items():
                if isinstance(value, dict) and "userErrors" in value:
                    ue = value["userErrors"]
                    if ue:
                        first = ue[0]
                        raise ShopifyUserError(
                            field=first.get("field", "unknown"),
                            message=first.get("message", "unknown"),
                            code=first.get("code"),
                        )

            return data

        # Exhausted retries
        raise last_exc or ShopifyThrottledError("Exhausted throttle retries")
