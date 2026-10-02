"""Print error messages for ALL T-117 children."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import GenerationJob, StoreBlueprint  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
for job in GenerationJob.objects.filter(parent=bp.build_job).order_by("page_type"):
    print(job.page_type, "|", job.status, "|", (job.error_message or "")[:250])
    for step in job.steps.filter(status="failed"):
        print("   failed step:", step.name, "|", str(step.output)[:200])
