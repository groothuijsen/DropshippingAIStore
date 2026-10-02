"""T-161 live E2E prep: PDP job state + fresh id_token."""

import os
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

import jwt as pyjwt  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import (  # noqa: E402
    GenerationJob,
    ManagedResource,
    Page,
)

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")

# PDP jobs + publish step state
pdps = GenerationJob.objects.filter(kind="page", page_type="pdp").order_by("-created_at")[:3]
for j in pdps:
    steps = list(j.steps.values_list("name", "status"))
    print("PDP JOB:", str(j.id)[:8], j.status, "|", j.input.get("product_gid"), "|", steps)

# Home page + MR state
home = Page.objects.filter(page_type="home").order_by("-created_at").first()
if home:
    print("HOME PAGE:", home.status, "| metaobjects:", home.metaobject_gids, "| shopify_page_gid:", repr(home.shopify_page_gid))
    mr = ManagedResource.objects.filter(shop=shop, gid__contains="Metaobject").values_list("gid", "handle")
    print("METAOBJECT MRs:", list(mr))

# ManagedResources overview
print("ALL MRs:", list(ManagedResource.objects.filter(shop=shop, removed_at__isnull=True).values_list("kind", "gid", "handle")))

# Fresh id_token
token = pyjwt.encode(
    {
        "iss": f"https://{shop.domain}/admin",
        "dest": f"https://{shop.domain}",
        "aud": settings.SHOPIFY_API_KEY,
        "sub": "1",
        "exp": 9999999999,
        "nbf": 1,
    },
    settings.SHOPIFY_API_SECRET,
    algorithm="HS256",
)
Path("/tmp/mosaiq_token.txt").write_text(token)
print("TOKEN saved")
