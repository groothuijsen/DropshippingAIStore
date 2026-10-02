"""T-114 live E2E — brand save → product ideas (real AI) → import window."""

import os
import time

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

import jwt  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import BlueprintStatus, StoreBlueprint  # noqa: E402
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


# Chain: route zero → brief → names → pick → brand → save → ideas
session.get(f"{BASE}/app/onboarding/brand/?id_token={token}", timeout=30)
session.post(
    f"{BASE}/app/onboarding/brand/?id_token={token}",
    data={"route": "zero"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
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
print("1) names:", len(bp.name_suggestions))

session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "pick_own", "own_name": "Helderz"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
deadline = time.time() + 180
while time.time() < deadline and not bp.brand_proposal:
    time.sleep(6)
    bp.refresh_from_db()
print("2) brand proposal:", "yes" if bp.brand_proposal else "NO")

prop = bp.brand_proposal or {}
pal = prop.get("palette", {})
if pal:
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
    bp.refresh_from_db()
    print("3) brand saved → bp.status:", bp.status)

# 3) Ideas: real product_ideas AI call (research model)
deadline = time.time() + 240
while time.time() < deadline and not bp.product_ideas:
    time.sleep(8)
    bp.refresh_from_db()
ideas = (bp.product_ideas or {}).get("ideas", [])
avoid = (bp.product_ideas or {}).get("avoid", [])
print(
    "4) ideas:",
    len(ideas),
    "| first:",
    ideas[0]["title"] if ideas else None,
    "| band:",
    ideas[0]["target_price_band"] if ideas else None,
    "| avoid:",
    len(avoid),
)

# 4) Ideas screen renders + deep link
r5 = session.get(f"{BASE}/app/start/?id_token={token}", timeout=30)
print(
    "5) ideas screen:",
    r5.status_code,
    "| ideas shown:",
    (ideas[0]["title"] in r5.text) if ideas else "n/a",
    "| avoid shown:",
    "Avoid in the EU" in r5.text,
    "| CJ link:",
    "cjdropshipping.com" in r5.text,
)

# 5) Start import → started_products_at (first click)
r6 = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "start_import"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print("6) start_import:", r6.status_code, "| started_products_at:", bp.started_products_at)
r7 = session.get(f"{BASE}/app/start/?id_token={token}", timeout=30)
print("7) window state shown:", "Import window opened" in r7.text)

# 6) Re-click keeps the window (first click wins)
first = bp.started_products_at
session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "start_import"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print("8) re-click keeps window:", bp.started_products_at == first)

print("E2E DONE")
