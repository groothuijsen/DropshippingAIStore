"""Diagnose products/update webhook delivery → PriceHistory."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.compliance.models import PriceHistory  # noqa: E402
from apps.core.models import Shop  # noqa: E402
from apps.webhooks.models import WebhookReceipt  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
print("recent receipts:")
for r in WebhookReceipt.objects.order_by("-received_at")[:8]:
    vid = None
    if r.body_json:
        variants = (r.body_json.get("variants") or []) if isinstance(r.body_json, dict) else []
        vid = variants[0].get("id") if variants else None
    print(
        " -",
        r.received_at,
        r.topic,
        r.shop_domain,
        "processed" if r.processed else "PENDING",
        "| variant:",
        vid,
    )

print("PriceHistory rows for shop:", PriceHistory.objects.filter(shop=shop).count())
