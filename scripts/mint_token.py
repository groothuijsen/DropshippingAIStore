"""Mint an id_token for the dev shop (T-160 live E2E screenshots)."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

import jwt as pyjwt  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
token = pyjwt.encode(
    {
        "iss": f"https://{shop.domain}/admin",
        "dest": f"https://{shop.domain}",
        "aud": settings.SHOPIFY_API_KEY,
        "sub": "1",
        "exp": 9999999999,
        "nbf": 1,
    },
    settings.SHOPIFY_API_SECRET,
    algorithm="HS256",
)
print(token)
