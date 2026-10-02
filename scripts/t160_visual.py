"""Collect what the visual walkthrough needs: product GIDs + routes."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.sources.models import ProductSource  # noqa: E402

for gid, src in ProductSource.objects.values_list("product_gid", "source")[:5]:
    print("PRODUCT:", gid, "|", src)
print("count:", ProductSource.objects.count())
