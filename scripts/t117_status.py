"""Quick build-status introspection for the dev store."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import GenerationJob, ManagedResource  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
for job in GenerationJob.objects.filter(shop=shop).order_by("-created_at")[:8]:
    print(job.kind, job.page_type or "-", job.status, job.error_code or "")
    for step in job.steps.all():
        err = (step.output or {}).get("last_error", "")
        print("   ", step.name, step.status + (f" — {err[:100]}" if err else ""))
print("MRs:", list(ManagedResource.objects.filter(shop=shop).values_list("kind", "handle")))
