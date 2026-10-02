"""Diagnose T-117 live failures."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.core.models import Shop  # noqa: E402
from apps.generator.models import GenerationJob  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
pdp = GenerationJob.objects.filter(shop=shop, page_type="pdp").order_by("-created_at").first()
print("PDP job error:", pdp.error_code, "|", (pdp.error_message or "")[:400])
research_step = pdp.steps.get(name="research")
print("research step output:", str(research_step.output)[:300])

home = GenerationJob.objects.filter(shop=shop, page_type="home").order_by("-created_at").first()
print("home input:", home.input)
print("home steps:", list(home.steps.values_list("name", "status")))
print("home error:", home.error_code, "|", (home.error_message or "")[:300])
