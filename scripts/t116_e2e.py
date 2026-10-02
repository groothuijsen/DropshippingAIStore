"""T-116 live E2E — re-confirm structure → standard pages → building panel."""

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
from apps.generator.tasks import generate_standard_pages  # noqa: E402

BASE = "http://172.16.0.213:8000"
HEADERS = {"Host": "shop.mosaiq.marketing"}

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
assert bp is not None
print("0) status:", bp.status, "| pages in structure:", (bp.store_structure or {}).get("pages"))

profiles = list(shop.delivery_profiles.all())
print("   delivery profiles:", [(p.source_app, p.ship_from_country) for p in profiles] or "none")

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
session.get(f"{BASE}/app/onboarding/brand/?id_token={token}", timeout=30)
ck = session.cookies.get("csrftoken", "")
csrf = {"X-CSRFToken": ck, "Cookie": f"csrftoken={ck}"}

if bp.status == BlueprintStatus.STRUCTURE:
    # Re-confirm the edited tree live: sets building + enqueues page content.
    r_conf = session.post(
        f"{BASE}/app/start/?id_token={token}",
        data={"action": "structure_confirm"},
        headers=csrf,
        timeout=30,
        allow_redirects=False,
    )
    bp.refresh_from_db()
    print("re-confirm:", r_conf.status_code, "| status:", bp.status)

if bp.status == BlueprintStatus.BUILDING and bp.standard_pages is None:
    generate_standard_pages.delay(str(bp.id))
    print("standard_pages task enqueued")

deadline = time.time() + 240
while time.time() < deadline and not bp.standard_pages:
    time.sleep(8)
    bp.refresh_from_db()

print("1) generated:", "yes" if bp.standard_pages else "NO")
if bp.standard_pages:
    for page_type, page in bp.standard_pages.items():
        types = [sec["type"] for sec in page["sections"]]
        print(f"   - {page_type}: '{page['title']}' sections={types} warnings={page['warnings']}")

r = session.get(f"{BASE}/app/start/?id_token={token}", timeout=30)
print(
    "2) building panel:",
    r.status_code,
    "| page listed:",
    ("Verzending" in r.text) or ("Retourneren" in r.text) or ("returns" in r.text),
    "| missing-facts warning:",
    "Missing facts" in r.text,
)

print("E2E DONE")
