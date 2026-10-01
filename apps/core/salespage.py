"""Public salespage for the Shopify app — served only on shopify.mosaiq.marketing.

Host-based routing: the embedded app backend (shop.mosaiq.marketing) must
never serve marketing content, and the salespage must not leak onto the
app subdomain. See docs/03-shopify-integration.md (app website URL).
"""

from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET

SALESPAGE_HOST = "shopify.mosaiq.marketing"


@require_GET
def salespage(request):
    """Render the Shopify app salespage on its dedicated subdomain."""
    host = request.get_host().split(":")[0]
    if host != SALESPAGE_HOST:
        raise Http404
    return render(request, "marketing/shopify_salespage.html")
