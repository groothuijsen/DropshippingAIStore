"""Session token validation middleware for Shopify embedded app.

See docs/03-shopify-integration.md §2.1–2.2.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import jwt
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

# Paths that do not require session token validation
EXEMPT_PATHS = {"/healthz/", "/admin/", "/webhooks/", "/proxy/"}


class SessionTokenMiddleware(MiddlewareMixin):
    """Validate Shopify session tokens on every admin request.

    - Full page GET (no HX-Request): accept id_token from query → validate.
      Missing/expired → bounce page (never 401 on document loads).
    - HTMX / fetch: Authorization header required. Invalid → 401.
    """

    def process_request(self, request: HttpRequest) -> HttpResponse | None:
        # Skip exempt paths
        if any(request.path.startswith(p) for p in EXEMPT_PATHS):
            return None

        # Only apply to /app/ routes
        if not request.path.startswith("/app/"):
            return None

        token = self._extract_token(request)
        if token is None:
            # Full page load without token → bounce
            if not request.headers.get("HX-Request"):
                return self._bounce(request)
            return self._unauthorized()

        try:
            payload = jwt.decode(
                token,
                settings.SHOPIFY_API_SECRET,
                algorithms=["HS256"],
                audience=settings.SHOPIFY_API_KEY,
                leeway=10,
            )
        except jwt.ExpiredSignatureError:
            if request.headers.get("HX-Request"):
                return self._unauthorized()
            return self._bounce(request)
        except jwt.InvalidTokenError as exc:
            logger.warning("Invalid session token: %s", exc)
            if request.headers.get("HX-Request"):
                return self._unauthorized()
            return self._bounce(request)

        # Validate dest and iss
        dest = payload.get("dest", "")
        if not dest.startswith("https://"):
            return self._unauthorized()

        iss = payload.get("iss", "")
        if not iss.startswith(dest) or not iss.endswith("/admin"):
            return self._unauthorized()

        # Extract shop domain
        parsed = urlparse(dest)
        shop_domain = parsed.hostname or ""
        if not shop_domain.endswith(".myshopify.com"):
            return self._unauthorized()

        # Store on request for views to use
        request.shop_domain = shop_domain  # type: ignore[attr-defined]
        request.session_token_payload = payload  # type: ignore[attr-defined]

        # Set UI locale from query param or shop primary locale
        request.ui_locale = request.GET.get("locale", "en")  # type: ignore[attr-defined]
        if request.ui_locale not in ("nl", "en", "de"):
            request.ui_locale = "en"  # type: ignore[attr-defined]

        return None  # continue to next middleware / view

    def _extract_token(self, request: HttpRequest) -> str | None:
        """Extract session token from Authorization header or id_token query param."""
        auth = request.META.get("HTTP_AUTHORIZATION", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return request.GET.get("id_token")

    def _bounce(self, request: HttpRequest) -> HttpResponse:
        """Render the bounce page which loads App Bridge and reloads with a new token."""
        return render(
            request,
            "app/bounce.html",
            {
                "shopify_api_key": settings.SHOPIFY_API_KEY,
                "current_url": request.build_absolute_uri(),
            },
        )

    def _unauthorized(self) -> HttpResponse:
        """Return 401 with the Shopify retry header."""
        response = HttpResponse(status=401)
        response["X-Shopify-Retry-Invalid-Session-Request"] = "1"
        return response
