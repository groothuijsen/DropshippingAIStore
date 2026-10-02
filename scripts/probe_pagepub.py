"""Probe pageUpdate isPublished on the live dev page."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient, load_query  # noqa: E402
from apps.core.tokens import decrypt_token  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), settings.SHOPIFY_API_VERSION)
data = client.execute(
    load_query("page_publish"),
    variables={"page": {"id": "gid://shopify/Page/170125230374", "isPublished": True}},
)
print("pageUpdate response:", data)
