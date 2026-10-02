"""Live webhook verification after the HMAC fix (F15-7 signal)."""

import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.crypto import decrypt_token  # noqa: E402
from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient, load_query  # noqa: E402
from apps.generator.models import BlueprintStatus, StoreBlueprint  # noqa: E402
from apps.webhooks.models import WebhookReceipt  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
bp = (
    StoreBlueprint.objects.filter(shop=shop)
    .order_by("-created_at")
    .first()
)
if bp is None or bp.started_products_at is None:
    from django.utils import timezone

    bp = StoreBlueprint.objects.create(
        shop=shop,
        status=BlueprintStatus.IDEAS,
        onboarding_route="zero",
        brand_name="Helderz",
        started_products_at=timezone.now(),
    )
    print("blueprint created for the test")
else:
    print("reusing blueprint", bp.id)

before_receipts = WebhookReceipt.objects.count()

client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), "2026-07")
create = client.execute(
    load_query("product_create_manual"),
    {"input": {"title": "T114 HMAC Fix Verification Product"}},
)
pc = create.get("productCreate") or create.get("productSet") or {}
gid = ((pc.get("product") or {}).get("id")) or ""
print("product created:", gid)

deadline = time.time() + 90
got_receipt = False
while time.time() < deadline:
    if WebhookReceipt.objects.count() > before_receipts:
        got_receipt = True
        break
    time.sleep(4)
print("webhook receipt arrived:", got_receipt)

bp.refresh_from_db()
recorded = any(item.get("gid") == gid for item in bp.imported_products or [])
print("blueprint imported_products recorded:", recorded)

if got_receipt:
    r = WebhookReceipt.objects.order_by("-received_at").first()
    print("latest receipt:", r.shop_domain, r.topic, "processed:", getattr(r, "processed_at", None))
print("VERIFY DONE")
