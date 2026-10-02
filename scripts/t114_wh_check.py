"""Check + re-register products/create webhook on the dev store (F15-7)."""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.crypto import decrypt_token  # noqa: E402
from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), "2026-07")

data = client.execute(
    """
    query { webhookSubscriptions(first: 20) { nodes { id topic } } }
    """,
    {},
)
subs = ((data.get("webhookSubscriptions") or {}).get("nodes")) or []
print("registered:")
for s in subs:
    print(" -", s.get("topic"), s.get("id"))

topics = {s.get("topic") for s in subs}
if "PRODUCTS_CREATE" not in topics:
    result = client.execute(
        """
        mutation WebhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $input: WebhookSubscriptionInput!) {
          webhookSubscriptionCreate(topic: $topic, input: $input) {
            webhookSubscription { id topic }
            userErrors { field message }
          }
        }
        """,
        {
            "topic": "PRODUCTS_CREATE",
            "input": {
                "uri": "https://shop.mosaiq.marketing/webhooks/shopify/",
                "includeFields": ["id", "title", "vendor", "created_at"],
            },
        },
    )
    print("re-registered PRODUCTS_CREATE:", json.dumps(result)[:300])
else:
    print("PRODUCTS_CREATE already registered")
