"""E2E data: write $app:mosaiq.delivery (product) + ship_cutoff settings (shop)."""
import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.conf import settings

from apps.core.crypto import decrypt_token
from apps.core.models import Shop

shop = Shop.objects.first()
token = decrypt_token(shop.access_token_encrypted)
import importlib

for name in ("apps.core.shopify_client", "apps.sources.shopify_client", "apps.generator.shopify_client"):
    try:
        mod = importlib.import_module(name)
        break
    except ImportError:
        continue
Client = mod.ShopifyGraphQLClient
client = Client(shop.domain, token, settings.SHOPIFY_API_VERSION)

mutation = """
mutation MetafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id key }
    userErrors { field message }
  }
}
"""

product_gid = "gid://shopify/Product/10781950181670"  # t114-hmac-fix-verification-product-1
result = client.execute(
    mutation,
    variables={
        "metafields": [
            {
                "ownerId": product_gid,
                "namespace": "$app:mosaiq",
                "key": "delivery",
                "type": "json",
                "value": json.dumps({
                    "by_market": {"NL": [4, 7], "BE": [4, 7], "DE": [5, 8]},
                    "default_market": "NL",
                    "ship_from": "CN",
                }),
            },
            {
                "ownerId": shop.shopify_gid,
                "namespace": "$app:mosaiq",
                "key": "settings",
                "type": "json",
                "value": json.dumps({
                    "ship_cutoff": {
                        "time": "23:59",
                        "days": ["mon", "tue", "wed", "thu", "fri"],
                        "delivery_days": 7,
                    }
                }),
            },
        ]
    },
)
print(json.dumps(result.get("metafieldsSet", {}), indent=1)[:700])
