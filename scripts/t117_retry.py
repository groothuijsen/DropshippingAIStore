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

failed = GenerationJob.objects.filter(parent=job, status=JobStatus.FAILED)
print("failed children:", list(failed.values_list("page_type", flat=True)))
for child in failed:
    retry_store_build_child.delay(str(child.id))
    print("retried:", child.page_type)

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
