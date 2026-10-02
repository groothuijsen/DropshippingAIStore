"""T-131 E2E part 2 — verify products/update webhook + PriceHistory snapshot."""

import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.compliance.models import PriceHistory  # noqa: E402
from apps.compliance.tasks import _get_client  # noqa: E402
from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import load_query  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
client = _get_client(shop)

# 1) What webhook subscriptions are actually registered?
subs = client.execute(
    """
    query { webhookSubscriptions(first: 25) {
      nodes { topic uri }
    } }"""
)
print("1) registered webhooks:")
for n in subs["webhookSubscriptions"]["nodes"]:
    print("  -", n["topic"], "->", n.get("uri"))

# 2) Re-check PriceHistory for the E2E variant (webhook may lag)
GID = "gid://shopify/Product/10781849714982"
data = client.execute(load_query("product_variants_by_product"), {"id": GID})
nodes = data.get("product", {}).get("variants", {}).get("nodes", [])
vid = nodes[0]["id"] if nodes else None
print("2) variant:", vid, "price:", nodes[0]["price"] if nodes else None)

time.sleep(5)
ph = PriceHistory.objects.filter(shop=shop, variant_gid=vid).order_by("-observed_at").first()
print("3) PriceHistory:", ph and (str(ph.price), ph.source, str(ph.observed_at)))

# 4) If products/update is missing → register it (T-110 v3 pattern: uri field)
topics = {n["topic"] for n in subs["webhookSubscriptions"]["nodes"]}
if "products/update" not in topics:
    # Args verified by live introspection 2026-10-02 (API 2026-07):
    # webhookSubscriptionCreate(topic:, webhookSubscription: {uri, format})
    reg = client.execute(
        """
        mutation Register($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
          webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
            webhookSubscription { id topic uri }
            userErrors { field message }
          }
        }""",
        {
            "topic": "PRODUCTS_UPDATE",
            "webhookSubscription": {
                "uri": "https://shop.mosaiq.marketing/webhooks/shopify/",
                "format": "JSON",
            },
        },
    )
    print("4) products/update registered:", reg["webhookSubscriptionCreate"]["webhookSubscription"])

    # 5) Re-apply the price to trigger products/update → PriceHistory.
    # Direct re-write via the same client call the view makes (price unchanged
    # would still emit products/update? Shopify skips no-op updates — bump then
    # restore to guarantee two update events, final price stays 24.95).
    from apps.core.shopify_client import load_query as lq

    client.execute(
        lq("product_variants_bulk_update"),
        {"productId": GID, "variants": [{"id": vid, "price": "24.96"}]},
    )
    time.sleep(3)
    client.execute(
        lq("product_variants_bulk_update"),
        {"productId": GID, "variants": [{"id": vid, "price": "24.95"}]},
    )
    time.sleep(10)
    ph = PriceHistory.objects.filter(shop=shop, variant_gid=vid).order_by("-observed_at").first()
    print("5) PriceHistory after re-apply:", ph and (str(ph.price), ph.source))
else:
    print("4) products/update already registered — no re-registration needed")

print("PART2 DONE")
