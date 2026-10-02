"""Introspect webhookSubscriptionCreate args (API 2026-07)."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from apps.compliance.tasks import _get_client  # noqa: E402
from apps.core.models import Shop  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
client = _get_client(shop)
data = client.execute(
    """
    query {
      __type(name: "Mutation") {
        fields {
          name
          args { name type { kind name ofType { kind name } } }
        }
      }
    }"""
)
for f in data["__type"]["fields"]:
    if f["name"] == "webhookSubscriptionCreate":
        for a in f["args"]:
            t = a["type"]
            tn = t.get("name") or (t.get("ofType") or {}).get("name")
            print("ARG:", a["name"], ":", t["kind"], tn)
        break

# Also introspect WebhookSubscriptionInput fields
data2 = client.execute(
    """
    query {
      __type(name: "WebhookSubscriptionInput") {
        inputFields { name type { kind name ofType { kind name } } }
      }
    }"""
)
print("WebhookSubscriptionInput fields:")
for f in data2["__type"]["inputFields"]:
    t = f["type"]
    tn = t.get("name") or (t.get("ofType") or {}).get("name")
    print("  -", f["name"], ":", t["kind"], tn)
