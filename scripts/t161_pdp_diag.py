"""Diagnose the PDP store-build child: pages + step outputs."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.generator.models import GenerationJob, Page  # noqa: E402

print("PAGES by type:", list(Page.objects.values_list("page_type", "shopify_page_gid")))
print("PDP job count:", GenerationJob.objects.filter(kind="page", page_type="pdp").count())
for j in GenerationJob.objects.filter(kind="page", page_type="pdp"):
    print("JOB", str(j.id)[:8], j.status, "| input gid:", j.input.get("product_gid"))
    for st in j.steps.all():
        print("   step:", st.name, st.status, "| out:", str(st.output)[:150])
