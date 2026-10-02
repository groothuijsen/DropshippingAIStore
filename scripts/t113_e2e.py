"""T-113 live E2E — names → brand proposal (real AI) → prefill → save → tokens."""

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


# 1) Route zero → wizard
session.get(f"{BASE}/app/onboarding/brand/?id_token={token}", timeout=30)
r = session.post(
    f"{BASE}/app/onboarding/brand/?id_token={token}",
    data={"route": "zero"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
print("1) route zero:", r.status_code)

# 2) Brief → names
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
print("2) names:", len(bp.name_suggestions))

# 3) Pick own name → enqueues brand proposal
r = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "pick_own", "own_name": "Helderz"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print("3) pick:", r.status_code, "| status:", bp.status, "| brand:", bp.brand_name)

# 4) Brand step: poll until proposal (real niche_brand AI call)
deadline = time.time() + 180
while time.time() < deadline and not bp.brand_proposal:
    time.sleep(6)
    bp.refresh_from_db()
prop = bp.brand_proposal or {}
print(
    "4) proposal:",
    "yes" if prop else "NO",
    "| tone:",
    prop.get("tone"),
    "| preset:",
    prop.get("style_preset"),
    "| font_h:",
    prop.get("font_heading"),
    "| tagline:",
    prop.get("tagline"),
)

# 5) Brand page prefill
r5 = session.get(f"{BASE}/app/onboarding/brand/?id_token={token}", timeout=30)
prefill_ok = prop and prop.get("palette", {}).get("primary", "XX") in r5.text
print(
    "5) brand page:",
    r5.status_code,
    "| proposal form:",
    "Your brand proposal" in r5.text,
    "| palette prefilled:",
    bool(prefill_ok),
)

# 6) Save brand (prefilled values)
if prop:
    pal = prop["palette"]
    r6 = session.post(
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
    bk = BrandKit.objects.filter(shop=shop).first()
    bp.refresh_from_db()
    print(
        "6) save:",
        r6.status_code,
        "| redirect:",
        (r6.headers.get("Location") or "")[:30],
        "| BrandKit:",
        bk and bk.brand_name,
        "| tagline:",
        bk and bk.tagline,
        "| bp.status:",
        bp.status,
        "| completed:",
        bp.completed_steps,
    )
    # 7) Wait for design-token sync (real metafieldsSet on dev store)
    deadline = time.time() + 90
    while time.time() < deadline and not (bk and bk.tokens_synced_at):
        time.sleep(5)
        bk.refresh_from_db()
    print("7) tokens_synced_at:", bk.tokens_synced_at if bk else None)
else:
    print("6) SKIPPED — no proposal to save")

print("E2E DONE")
