"""T-112 live E2E — route choice → brief → names (real AI) → pick name."""

import os
import time

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

import jwt  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import StoreBlueprint  # noqa: E402

# Hairpin loop: call gunicorn directly with the real Host header.
BASE = "http://172.16.0.213:8000"
HEADERS = {"Host": "shop.mosaiq.marketing"}

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
# Reset onboarding state for a clean run
shop.onboarding_step = "brand"
shop.onboarding_route = ""
shop.save(update_fields=["onboarding_step", "onboarding_route"])
StoreBlueprint.objects.filter(shop=shop).delete()
print("0) state reset: step=brand route='' blueprints cleared")

token = jwt.encode(
    {
        "iss": f"https://{shop.domain}/admin",
        "dest": f"https://{shop.domain}",
        "aud": settings.SHOPIFY_API_KEY,
        "sub": "12345",
        "exp": int(time.time()) + 600,
        "nbf": int(time.time()) - 60,
    },
    settings.SHOPIFY_API_SECRET,
    algorithm="HS256",
)

session = requests.Session()
session.headers.update(HEADERS)


def csrf_headers() -> dict:
    return {"X-CSRFToken": session.cookies.get("csrftoken", ""), "Cookie": f"csrftoken={session.cookies.get('csrftoken', '')}"}


# 1) Brand step renders route choice
r1 = session.get(f"{BASE}/app/onboarding/brand/?id_token={token}", timeout=30)
print("1) brand step GET:", r1.status_code, "| route choice:", "Start from zero" in r1.text)

# 2) Choose route zero → wizard
r2 = session.post(
    f"{BASE}/app/onboarding/brand/?id_token={token}",
    data={"route": "zero"},
    headers=csrf_headers(),
    timeout=30,
    allow_redirects=False,
)
shop.refresh_from_db()
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
print(
    "2) route zero POST:",
    r2.status_code,
    "| location:",
    (r2.headers.get("Location") or "")[:40],
    "| shop.route:",
    shop.onboarding_route,
    "| blueprint:",
    bp and bp.status,
)

# 3) Brief screen + submit valid brief
r3 = session.get(f"{BASE}/app/start/?id_token={token}", timeout=30)
print("3) wizard GET:", r3.status_code, "| brief form:", "Build your store from zero" in r3.text)

r4 = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={
        "action": "brief",
        "description": "Sleep wellness products for people who struggle to fall asleep at night.",
        "markets": ["NL", "BE"],
        "content_locales": ["nl"],
        "audience": "Adults 25-45 with sleep problems",
        "price_level": "mid",
        "import_app": "cj",
    },
    headers=csrf_headers(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print("4) brief POST:", r4.status_code, "| blueprint status:", bp.status, "| markets:", bp.markets)

# 4) Poll for name suggestions (real AI call via Celery worker)
deadline = time.time() + 180
while time.time() < deadline and not bp.name_suggestions:
    time.sleep(6)
    bp.refresh_from_db()
names = [n["name"] for n in bp.name_suggestions]
statuses = [n["domain_status"] for n in bp.name_suggestions]
print("5) names after poll:", len(names), names, "| domains:", statuses)

# 6) Panel renders the names
r6 = session.get(f"{BASE}/app/start/panel/?id_token={token}", timeout=30)
print(
    "6) panel GET:",
    r6.status_code,
    "| has names:",
    all(n in r6.text for n in names[:3]) if names else "n/a (still generating)",
    "| disclaimer:",
    "Not a trademark check" in r6.text,
)

# 7) Pick own name → brand step
r7 = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "pick_own", "own_name": "Helderz"},
    headers=csrf_headers(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print(
    "7) pick_own POST:",
    r7.status_code,
    "| brand_name:",
    bp.brand_name,
    "| slug:",
    bp.brand_slug,
    "| status:",
    bp.status,
    "| completed:",
    bp.completed_steps,
)

print("E2E DONE")
