"""Direct signed products/update webhook test → receiver → PriceHistory."""

import base64
import hashlib
import hmac
import json
import os
import time

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.conf import settings  # noqa: E402

from apps.compliance.models import PriceHistory  # noqa: E402
from apps.core.models import Shop  # noqa: E402
from apps.webhooks.models import WebhookReceipt  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
GID = "gid://shopify/Product/10781849714982"
VID = "gid://shopify/ProductVariant/53992323940646"

body = {
    "id": 10781849714982,
    "title": "T131 E2E Test Product",
    "admin_graphql_api_id": GID,
    "variants": [
        {
            "id": 53992323940646,
            "product_id": 10781849714982,
            "price": "24.95",
            "sku": "",
            "admin_graphql_api_id": VID,
        }
    ],
}
raw = json.dumps(body).encode()
digest = hmac.new(settings.SHOPIFY_API_SECRET.encode(), raw, hashlib.sha256).digest()
sig = base64.b64encode(digest).decode()

resp = requests.post(
    "http://172.16.0.213:8000/webhooks/shopify/",
    data=raw,
    headers={
        "Host": "shop.mosaiq.marketing",
        "Content-Type": "application/json",
        "X-Shopify-Topic": "products/update",
        "X-Shopify-Hmac-Sha256": sig,
        "X-Shopify-Shop-Domain": "mosaiq-pod.myshopify.com",
        "X-Shopify-Webhook-Id": "t131-direct-test-001",
    },
    timeout=30,
)
print("1) receiver HTTP:", resp.status_code, resp.text[:120])

time.sleep(3)
r = WebhookReceipt.objects.filter(webhook_id="t131-direct-test-001").first()
print("2) receipt:", r and (r.topic, r.shop_domain, r.processed))
ph = PriceHistory.objects.filter(shop=shop, variant_gid=VID).order_by("-observed_at").first()
print("3) PriceHistory:", ph and (str(ph.price), ph.source, str(ph.observed_at)))
print("DIAG DONE")
