"""T-161 live E2E: re-run PDP publish with GPSR in the metafield + home MR repair."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.compliance.gpsr_loader import load_gpsr_info  # noqa: E402
from apps.core.models import AuditLog, Shop  # noqa: E402
from apps.generator.models import (  # noqa: E402
    GenerationJob,
    JobStatus,
    ManagedResource,
    Page,
    StepStatus,
)
from apps.generator.tasks import run_job  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")

# 1. Gate sees complete GPSR
from django.conf import settings  # noqa: E402

from apps.core.crypto import decrypt_token  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient  # noqa: E402

client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), settings.SHOPIFY_API_VERSION)
info = load_gpsr_info(client, "gid://shopify/Product/10781946347814")
print("GATE GPSR complete:", info.complete, "| missing:", info.missing_fields)

# 2. Re-run the PDP publish step with the new code
pdps = GenerationJob.objects.filter(kind="page", page_type="pdp").order_by("-created_at")
job = None
page = None
for candidate in pdps:
    page = Page.objects.filter(job=candidate).first()
    if page is not None:
        job = candidate
        break
if job is None:
    print("NO PDP JOB WITH PAGE")
else:
    print("PDP page:", page.page_type, page.status, "gid:", repr(page.shopify_page_gid))
    step = job.steps.filter(name="publish").first()
    step.status = StepStatus.PENDING
    step.error_code = ""
    step.error_message = ""
    step.output = None
    step.save(update_fields=["status", "error_code", "error_message", "output", "updated_at"])
    job.status = JobStatus.RUNNING
    job.save(update_fields=["status", "updated_at"])
    result = run_job.run(str(job.id))
    step.refresh_from_db()
    job.refresh_from_db()
    print("PUBLISH STEP:", step.status, "| job:", job.status, "| job.error:", job.error_code)
    print("STEP OUTPUT (truncated):", str(step.output)[:400])

# 3. Home MR repair — register the home metaobject as a managed resource
home = Page.objects.filter(page_type="home", shop=shop).order_by("-created_at").first()
if home and home.metaobject_gids:
    gid = next(iter(home.metaobject_gids.values()))
    from apps.generator.models import StoreBlueprint

    bp_for_home = StoreBlueprint.objects.filter(build_job=home.job.parent_id and home.job.parent).first()
    mr, created = ManagedResource.objects.get_or_create(
        shop=shop,
        gid=gid,
        defaults={
            "blueprint": bp_for_home,
            "kind": ManagedResource.Kind.PAGE,
            "handle": home.metaobject_handles.get("nl") or f"mq-home-{str(home.id)[:8]}",
            "title": home.title,
        },
    )
    print("HOME MR:", "created" if created else "exists", mr.gid, mr.handle)
else:
    print("HOME PAGE:", home, home.metaobject_gids if home else None)

# 4. AuditLog check
print("GPSR AUDIT:", list(AuditLog.objects.filter(shop=shop, action="gpsr_saved").values_list("action", "payload")[:3]))

# 5. Final MR overview
print("ALL MRs:", list(ManagedResource.objects.filter(shop=shop, removed_at__isnull=True).values_list("kind", "gid")))
