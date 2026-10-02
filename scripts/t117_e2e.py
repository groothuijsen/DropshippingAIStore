"""T-117 live E2E — store build on the dev shop.

Runs from inside CT 412: re-confirm the wizard path is already done
(status=building with standard_pages), so this script clicks "Build my
store" over HTTP (CSRF pattern), waits for the parent job, and reports
every step, child, collection and the menu.
"""

import os
import time

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

import jwt  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import (  # noqa: E402
    GenerationJob,
    JobStatus,
    ManagedResource,
    StoreBlueprint,
)

BASE = "http://172.16.0.213:8000"
HEADERS = {"Host": "shop.mosaiq.marketing"}

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
assert bp is not None
print("0) status:", bp.status, "| products:", len(bp.selected_product_gids or []), "| pages ready:", bool(bp.standard_pages))

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

r = session.post(
    f"{BASE}/app/start/?id_token={token}",
    data={"action": "build_store"},
    headers=csrf,
    timeout=30,
    allow_redirects=False,
)
print("1) build click:", r.status_code)

deadline = time.time() + 300
while time.time() < deadline:
    bp.refresh_from_db()
    job = bp.build_job
    if job and job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        break
    time.sleep(8)

job = bp.build_job
print("2) parent:", job.status if job else "NONE", "|", job.error_code if job and job.error_code else "")
if job:
    for step in job.steps.all():
        err = (step.output or {}).get("last_error", "")
        print(f"   step {step.name}: {step.status}" + (f" — {err[:120]}" if err else ""))
    children = GenerationJob.objects.filter(parent=job)
    for child in children:
        print(f"   child {child.page_type}: {child.status}" + (f" — {child.error_message[:100]}" if child.error_message else ""))
    mrs = ManagedResource.objects.filter(shop=shop, blueprint=bp)
    print("3) managed resources:", [(m.kind, m.handle) for m in mrs])

print("E2E DONE")
