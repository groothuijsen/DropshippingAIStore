"""CSP and frame-ancestors middleware for Shopify embedded app.

See docs/03-shopify-integration.md §2.5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.deprecation import MiddlewareMixin

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


class CspFrameAncestorsMiddleware(MiddlewareMixin):
    """Set Content-Security-Policy frame-ancestors per shop domain.

    Only applies to /app/ routes. Other routes get the default CSP.
    """

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        if not request.path.startswith("/app/"):
            return response

        shop_domain = getattr(request, "shop_domain", None)
        if shop_domain:
            response["Content-Security-Policy"] = f"frame-ancestors https://{shop_domain} https://admin.shopify.com;"
        else:
            # Fallback: allow Shopify admin only
            response["Content-Security-Policy"] = "frame-ancestors https://admin.shopify.com;"

        return response
