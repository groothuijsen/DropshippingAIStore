"""T-131 live E2E v3 — creates a fresh dev-store product, then calc + apply.

Runs on CT 412 with prod settings, real HTTP to gunicorn (Host header set),
real GraphQL writes to the dev store mosaiq-pod.myshopify.com.
"""

import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

import jwt  # noqa: E402
import requests  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.compliance.models import PriceAdvice, PriceHistory  # noqa: E402
from apps.compliance.tasks import _get_client  # noqa: E402
from apps.core.models import AuditLog, Shop  # noqa: E402
from apps.core.shopify_client import load_query  # noqa: E402
from apps.sources.models import ProductSource  # noqa: E402

# Hairpin loop: from inside CT 412 the public domain doesn't route back
# through Traefik — call gunicorn directly with the real Host header.
BASE = "http://172.16.0.213:8000"
HEADERS = {"Host": "shop.mosaiq.marketing"}

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")

# 1) Create a fresh test product on the dev store
client = _get_client(shop)
created = client.execute(
    load_query("product_create_manual"),
    {
        "input": {
            "title": "T131 E2E Test Product",
            "descriptionHtml": "<p>Temporary product for T-131 price-apply E2E.</p>",
            "status": "DRAFT",
            "vendor": "Mosaiq Dev",
        }
    },
)
prod = created["productSet"]["product"]
GID = prod["id"]
print("1) product created:", prod["id"], "|", prod["title"], "|", prod["status"])

# 2) ProductSource — this product IS created by Mosaiq
ps = ProductSource.objects.create(
    shop=shop,
    product_gid=GID,
    source="manual",
    detected_by="mosaiq",
    created_by_mosaiq=True,
    locked_fields=[],
)
print("2) ProductSource created: manual/mosaiq/created_by_mosaiq=True")

GID_URL = GID.replace(":", "%3A").replace("/", "%2F")
token = jwt.encode(
    {
        "iss": f"https://{shop.domain}/admin",
        "dest": f"https://{shop.domain}",
        "aud": settings.SHOPIFY_API_KEY,
        "sub": "12345",
        "exp": int(time.time()) + 300,
        "nbf": int(time.time()) - 60,
    },
    settings.SHOPIFY_API_SECRET,
    algorithm="HS256",
)

# 3) Warm GET (CSRF cookie) + calc advice
session = requests.Session()
session.headers.update(HEADERS)
warm = session.get(
    f"{BASE}/app/products/{GID_URL}/pricing/?id_token={token}",
    timeout=30,
)
csrf = session.cookies.get("csrftoken", "")
# CSRF_COOKIE_SECURE=True: the jar won't replay the cookie over plain http —
# send it explicitly in the Cookie header alongside X-CSRFToken.
post_headers = {"X-CSRFToken": csrf, "Cookie": f"csrftoken={csrf}"}
print("3) warm GET:", warm.status_code, "| csrf cookie:", bool(csrf))

resp = session.post(
    f"{BASE}/app/products/{GID_URL}/pricing/?id_token={token}",
    data={"cost": "8.00", "shipping": "4.00", "market": "NL"},
    headers=post_headers,
    timeout=30,
)
content = resp.text
print(
    "4) calc:",
    resp.status_code,
    "| has 24.95:",
    "24.95" in content,
    "| has Omnibus:",
    "30 days before the discount" in content,
)

adv = PriceAdvice.objects.filter(shop=shop, product_gid=GID).order_by("-created_at").first()
print("5) PriceAdvice:", adv.id, "| applied_at:", adv.applied_at)

# 6) Apply — real price write to the dev store
resp2 = session.post(
    f"{BASE}/app/products/{GID_URL}/pricing/apply/?id_token={token}",
    data={"advice_id": str(adv.id)},
    headers=post_headers,
    timeout=30,
    allow_redirects=False,
)
adv.refresh_from_db()
print(
    "6) apply:",
    resp2.status_code,
    "| applied_at:",
    adv.applied_at,
    "| applied_price:",
    adv.applied_price,
)

# 7) Verify live price via Admin API
data = client.execute(load_query("product_variants_by_product"), {"id": GID})
nodes = data.get("product", {}).get("variants", {}).get("nodes", [])
print("7) live price on dev store:", [n["price"] for n in nodes])

log = AuditLog.objects.filter(shop=shop, action="price_advisor_applied").order_by("-created_at").first()
print("8) AuditLog:", log and log.payload)

# 9) Omnibus webhook check — products/update should snapshot PriceHistory
time.sleep(10)
if nodes:
    ph = (
        PriceHistory.objects.filter(shop=shop, variant_gid=nodes[0]["id"])
        .order_by("-observed_at")
        .first()
    )
    print("9) PriceHistory latest:", ph and (str(ph.price), ph.source))

print("E2E DONE — product left on dev store as", GID)
