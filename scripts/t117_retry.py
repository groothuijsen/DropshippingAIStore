"""Retry the failed T-117 children on the dev store and report the outcome."""

import os
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import (  # noqa: E402
    GenerationJob,
    JobStatus,
    ManagedResource,
    StoreBlueprint,
)
from apps.generator.tasks import retry_store_build_child, run_store_build  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
job = bp.build_job
print("parent:", job.status)

from apps.generator.models import JobStep, StepStatus  # noqa: E402

stuck_ids = JobStep.objects.filter(
    job__parent=job, status=StepStatus.FAILED
).values_list("job_id", flat=True)
from django.db.models import Q  # noqa: E402

failed = GenerationJob.objects.filter(parent=job).filter(
    Q(status__in=[JobStatus.FAILED, JobStatus.NEEDS_INPUT]) | Q(id__in=stuck_ids)
)
print("failed/stuck children:", list(failed.values_list("page_type", flat=True)))
for child in failed:
    # Layout output is checkpointed: pre-fix runs stored the old
    # per-section field keys, which poison publish on retry. Reset
    # layout to pending so it re-runs with the current code.
    child.steps.filter(name="layout").update(status=StepStatus.PENDING, output=None)
    retry_store_build_child.delay(str(child.id))
    print("retried:", child.page_type)

# Diagnose the PDP research checkpoint (auto-angle depends on its angles)
pdp = GenerationJob.objects.filter(parent=job, page_type="pdp").first()
if pdp:
    rs = pdp.steps.filter(name="research").first()
    out = (rs.output if rs else None) or {}
    print("pdp research output keys:", list(out.keys()), "| angles:", len(out.get("angles", [])), "| status:", pdp.status)

# If the parent itself failed at a step (not children), re-run the parent
if job.status == JobStatus.FAILED:
    run_store_build.delay(str(bp.id))
    print("parent re-enqueued")

deadline = time.time() + 420
while time.time() < deadline:
    job.refresh_from_db()
    bp.refresh_from_db()
    running = GenerationJob.objects.filter(parent=job).exclude(
        status__in=[JobStatus.SUCCEEDED, JobStatus.FAILED]
    )
    if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED) and not running.exists():
        break
    time.sleep(10)

print("final parent:", job.status, "|", job.error_code or "")
for child in GenerationJob.objects.filter(parent=job):
    print("  child", child.page_type, child.status, (child.error_message or "")[:120])
for step in job.steps.all():
    err = (step.output or {}).get("last_error", "")
    print("  step", step.name, step.status + (f" — {err[:100]}" if err else ""))
print("MRs:", list(ManagedResource.objects.filter(shop=shop, blueprint=bp).values_list("kind", "handle")))
print("DONE")
