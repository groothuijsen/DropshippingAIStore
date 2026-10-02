"""Read-only diagnosis: which products exist and which template they use."""
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

try:
    from apps.core.shopify_client import ShopifyGraphQLClient
except ImportError:
    from apps.sources.shopify_client import ShopifyGraphQLClient  # noqa: F401

import importlib
mod = None
for name in ("apps.core.shopify_client", "apps.sources.shopify_client", "apps.generator.shopify_client"):
    try:
        mod = importlib.import_module(name)
        break
    except ImportError:
        continue

Client = getattr(mod, "ShopifyGraphQLClient")
client = Client(shop.domain, token, settings.SHOPIFY_API_VERSION)
query = """
query {
  products(first: 10) {
    nodes { id title templateSuffix handle }
  }
}
"""
result = client.execute(query) if hasattr(client, "execute") else client.execute_query(query)
print(json.dumps(result, indent=1)[:1200])
