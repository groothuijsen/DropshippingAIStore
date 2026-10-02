"""T-161 live E2E part 2: run the PDP child for real with GPSR complete."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import (  # noqa: E402
    GenerationJob,
    JobStatus,
    ManagedResource,
    Page,
    StepStatus,
)
from apps.generator.tasks import run_store_build_child  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")

job = None
page = None
for candidate in GenerationJob.objects.filter(kind="page", page_type="pdp").order_by("-created_at"):
    page = Page.objects.filter(job=candidate).first()
    if page is not None:
        job = candidate
        break
if job is None:
    # No Page yet — pick the single PDP job (the one with research output)
    job = GenerationJob.objects.filter(kind="page", page_type="pdp").order_by("-created_at").first()

print("JOB:", str(job.id)[:8], job.status, "| angle_id:", (job.input or {}).get("angle_id"))

# Ensure chosen_angle exists (the historical gap that made copy return None)
research = job.steps.filter(name="research").first()
angles = (research.output or {}).get("angles", []) if research and research.output else []
if angles and not (research.output or {}).get("chosen_angle"):
    from apps.generator.research_step import select_angle

    chosen = angles[0].get("id")
    print("Setting angle:", chosen)
    select_angle(job, chosen)
    job.refresh_from_db()
elif not angles:
    print("NO ANGLES in research output:", str(research.output)[:200] if research else None)

# Reset copy..publish to pending so the fixed pipeline runs for real
for name in ("images", "compliance_check", "layout", "publish"):  # copy already succeeded with real output
    st = job.steps.filter(name=name).first()
    if st:
        st.status = StepStatus.PENDING
        st.output = None
        st.save(update_fields=["status", "output", "updated_at"])
job.status = JobStatus.RUNNING
job.save(update_fields=["status", "updated_at"])

run_store_build_child(str(job.id))

job.refresh_from_db()
print("FINAL JOB:", job.status, "| error:", job.error_code, job.error_message[:120] if job.error_message else "")
for st in job.steps.all():
    print("  step:", st.name, st.status, "| out:", str(st.output)[:110])
page = Page.objects.filter(job=job).first()
print("PAGE:", page.page_type if page else None, page.status if page else None,
      "gid:", repr(page.shopify_page_gid) if page else None,
      "metaobjects:", page.metaobject_gids if page else None)
bp_id = (job.input or {}).get("blueprint_id")
if bp_id:
    print("MRs:", list(ManagedResource.objects.filter(shop=shop, blueprint_id=bp_id, removed_at__isnull=True).values_list("kind", "gid")))
