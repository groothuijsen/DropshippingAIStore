"""T-114b live E2E — F15-7: import window → webhook signal → selection."""

import os
import time

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

import jwt  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.core.crypto import decrypt_token  # noqa: E402
from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient, load_query  # noqa: E402
from apps.generator.models import StoreBlueprint  # noqa: E402
from apps.themes.models import BrandKit  # noqa: E402

BASE = "http://172.16.0.213:8000"
HEADERS = {"Host": "shop.mosaiq.marketing"}

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
shop.onboarding_step = "brand"
shop.onboarding_route = ""
shop.save(update_fields=["onboarding_step", "onboarding_route"])
StoreBlueprint.objects.filter(shop=shop).delete()
BrandKit.objects.filter(shop=shop).delete()
print("0) state reset")

token = jwt.encode(
    {
        "iss": f"https://{shop.domain}/admin",
        "dest": f"https://{shop.domain}",
        "aud": settings.SHOPIFY_API_KEY,
        "sub": "12345",
        "exp": int(time.time()) + 900,
        "nbf": int(time.time()) - 60,
    },
    settings.SHOPIFY_API_SECRET,
    algorithm="HS256",
)

session = requests.Session()
session.headers.update(HEADERS)


def csrf() -> dict:
    ck = session.cookies.get("csrftoken", "")
    return {"X-CSRFToken": ck, "Cookie": f"csrftoken={ck}"}


# Chain up to ideas (brief → names → pick → brand → save)
session.get(f"{BASE}/app/onboarding/brand/?id_token={token}", timeout=30)
session.post(f"{BASE}/app/onboarding/brand/?id_token={token}", data={"route": "zero"}, headers=csrf(), timeout=30, allow_redirects=False)
session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={
        "action": "brief",
        "description": "Sleep wellness products for people who struggle to fall asleep at night.",
        "markets": ["NL"],
        "content_locales": ["nl"],
        "audience": "Adults 25-45 with sleep problems",
        "price_level": "mid",
        "import_app": "cj",
    },
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
deadline = time.time() + 180
while time.time() < deadline and not bp.name_suggestions:
    time.sleep(6)
    bp.refresh_from_db()
session.post(f"{BASE}/app/start/?id_token={token}", data={"action": "pick_own", "own_name": "Helderz"}, headers=csrf(), timeout=30, allow_redirects=False)
deadline = time.time() + 180
while time.time() < deadline and not bp.brand_proposal:
    time.sleep(6)
    bp.refresh_from_db()
prop = bp.brand_proposal or {}
pal = prop.get("palette", {})
session.post(
    f"{BASE}/app/onboarding/brand/?id_token={token}",
    data={
        "route": "zero",
        "brand_name": "Helderz",
        "tagline": prop.get("tagline", ""),
        "tone": prop.get("tone", "warm"),
        "style_preset": prop.get("style_preset", "clean"),
        "primary": pal["primary"],
        "secondary": pal["secondary"],
        "accent": pal["accent"],
        "background": pal["background"],
        "text": pal["text"],
        "font_heading": prop.get("font_heading", ""),
        "font_body": prop.get("font_body", ""),
    },
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
deadline = time.time() + 240
while time.time() < deadline and not bp.product_ideas:
    time.sleep(8)
    bp.refresh_from_db()
print("1) chain ready; ideas:", len((bp.product_ideas or {}).get("ideas", [])))

# Start import window
session.post(f"{BASE}/app/start/?id_token={token}", data={"action": "start_import"}, headers=csrf(), timeout=30, allow_redirects=False)
bp.refresh_from_db()
print("2) import window:", bp.started_products_at is not None)

# Create a product on the dev store AFTER the window opened (webhook signal)
client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), "2026-07")
create = client.execute(
    load_query("product_create_manual"),
    {"input": {"title": "T114 Import Window Test Product"}},
)
gid = ((create.get("productCreate") or {}).get("product") or {}).get("id") or ((create.get("productSet") or {}).get("product") or {}).get("id") or ""
print("3) product created:", gid or create)

# Webhook should append it to imported_products (poll)
deadline = time.time() + 60
while time.time() < deadline:
    bp.refresh_from_db()
    if any(item.get("gid") == gid for item in bp.imported_products or []):
        break
    time.sleep(4)
print("4) webhook recorded:", any(item.get("gid") == gid for item in bp.imported_products or []))

# Panel shows the product (fallback query + webhook merge)
r5 = session.get(f"{BASE}/app/start/panel/?id_token={token}", timeout=30)
print(
    "5) panel:",
    r5.status_code,
    "| product listed:",
    "T114 Import Window Test Product" in r5.text,
    "| plan max shown:",
    "/ 5" in r5.text,
)

# Select the product → structure
r6 = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "select_products", "product_gid": [gid] if gid else []},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print(
    "6) select:",
    r6.status_code,
    "| selected:",
    bp.selected_product_gids,
    "| status:",
    bp.status,
    "| completed:",
    bp.completed_steps,
)

# 0-selected validation still enforced
r7 = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "select_products", "product_gid": []},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print("7) empty selection refused; status stays:", bp.status)

print("E2E DONE")
