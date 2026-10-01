"""Public salespage for the Shopify app — served only on shopify.mosaiq.marketing.

Host-based routing:
- shopify.mosaiq.marketing → marketing salespage
- shop.mosaiq.marketing → redirect root to /app/ (embedded app entry point)
- any other host → 404

See docs/03-shopify-integration.md §2.1 (application_url must point at the
embedded app; Shopify loads it in the admin iframe with shop/host/session
query params that must survive the redirect).
"""

from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_GET

SALESPAGE_HOST = "shopify.mosaiq.marketing"
APP_HOST = "shop.mosaiq.marketing"


@require_GET
def salespage(request):
    """Route by host: salespage, app-root redirect, or 404."""
    host = request.get_host().split(":")[0]

    if host == APP_HOST:
        # Shopify opens application_url in the admin iframe. The app lives
        # on /app/; the root must redirect there with all query params
        # (shop, host, session, id_token) intact.
        qs = request.META.get("QUERY_STRING", "")
        target = "/app/" + (f"?{qs}" if qs else "")
        response = HttpResponseRedirect(target)
        # Allow the Shopify admin to frame the redirect response.
        shop = request.GET.get("shop", "")
        ancestors = "https://admin.shopify.com"
        if shop:
            ancestors = f"https://{shop} https://admin.shopify.com"
        response["Content-Security-Policy"] = f"frame-ancestors {ancestors};"
        return response

    if host != SALESPAGE_HOST:
        raise Http404

    return render(request, "marketing/shopify_salespage.html")
