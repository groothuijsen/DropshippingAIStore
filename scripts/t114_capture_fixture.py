"""Capture a real products_list response as a fixture (AGENTS.md §5)."""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.crypto import decrypt_token  # noqa: E402
from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient, load_query  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
token = decrypt_token(shop.access_token_encrypted)
client = ShopifyGraphQLClient(shop.domain, token, "2026-07")
data = client.execute(load_query("products_list"), {"first": 3})
with open("/tmp/products_list_fixture.json", "w") as f:
    json.dump(data, f, indent=2)
nodes = (data.get("products") or {}).get("nodes") or []
print("captured", len(nodes), "products; first createdAt:", nodes[0].get("createdAt") if nodes else None)
