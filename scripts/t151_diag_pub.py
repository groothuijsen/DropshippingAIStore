"""Read-only: publication status of the dev-store products."""
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
result = client.execute("""
query {
  publications(first: 5) { nodes { id name } }
  products(first: 5) {
    nodes {
      id title
      publications(first: 3) { nodes { isPublished channel { id name } } }
    }
  }
}
""")
print(json.dumps(result, indent=1)[:1500])
