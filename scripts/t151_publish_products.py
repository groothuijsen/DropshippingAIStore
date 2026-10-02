"""Publish dev-store products to the Online Store channel (theme editor preview).

The theme editor cannot open the Default product template when no product is
published to Online Store. publishablePublish is a known operation (fixtures
in publish_step flow).
"""
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

pubs = client.execute("query { publications(first: 10) { nodes { id name } } }")
online_store = None
for node in pubs.get("publications", {}).get("nodes", []):
    print("publication:", node.get("name"), node.get("id"))
    if node.get("name") == "Online Store":
        online_store = node["id"]
if not online_store:
    raise SystemExit("Online Store publication not found")

products = client.execute("query { products(first: 10) { nodes { id title } } }")
mutation = """
mutation PublishablePublish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) {
    userErrors { field message }
  }
}
"""
for product in products.get("products", {}).get("nodes", []):
    result = client.execute(
        mutation,
        variables={
            "id": product["id"],
            "input": [{"publicationId": online_store}],
        },
    ) if hasattr(client, "execute") and client.execute.__code__.co_argcount >= 2 else None
    if result is None:
        # execute() may not accept variables — fall back to inlined query
        inlined = mutation.replace("$id", f"'{product['id']}'").replace("$input", f"[{{publicationId: '{online_store}'}}]")
        inlined = inlined.replace("mutation publish(id: ID!, input: [PublicationInput!]!) {", "mutation {")
        result = client.execute(inlined)
    errors = (result.get("publishablePublish") or {}).get("userErrors") or []
    print(product["title"], "->", "ERRORS: " + json.dumps(errors) if errors else "published")
