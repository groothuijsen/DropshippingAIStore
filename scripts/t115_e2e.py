"""T-115 live E2E — structure proposal (real AI) → edits → confirm."""

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
from apps.generator.tasks import generate_store_structure  # noqa: E402

BASE = "http://172.16.0.213:8000"
HEADERS = {"Host": "shop.mosaiq.marketing"}

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
assert bp is not None and bp.selected_product_gids, "no blueprint with selection"
print("0) blueprint:", bp.id, "| status:", bp.status, "| selected:", len(bp.selected_product_gids))

if bp.status == BlueprintStatus.STRUCTURE and bp.store_structure is None:
    generate_store_structure.delay(str(bp.id))
    print("structure task enqueued")

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


deadline = time.time() + 240
while time.time() < deadline and not bp.store_structure and not bp.structure_error:
    time.sleep(8)
    bp.refresh_from_db()
print("1) proposal:", "yes" if bp.store_structure else f"no ({bp.structure_error})")

if not bp.store_structure:
    raise SystemExit(1)

structure = bp.store_structure
print(
    "   collections:",
    [c["title"] for c in structure["collections"]],
    "| menu:",
    len(structure["menu"]),
    "| pages:",
    structure["pages"],
)

# Edit: rename first collection
r2 = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "structure_rename", "item_type": "collection", "index": "0", "field": "title", "value": "Hernoemd door test"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print("2) rename:", r2.status_code, "| first collection:", bp.store_structure["collections"][0]["title"])

# Confirm → building
r3 = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "structure_confirm"},
    headers=csrf(),
    timeout=30,
    allow_redirects=False,
)
bp.refresh_from_db()
print("3) confirm:", r3.status_code, "| status:", bp.status, "| completed:", bp.completed_steps)

print("E2E DONE")
