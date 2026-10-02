"""Introspect metaobjectUpsert + Metaobject types on API 2026-07 (deviation rule)."""

import json
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient  # noqa: E402
from apps.core.tokens import decrypt_token  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), settings.SHOPIFY_API_VERSION)

INTROSPECT = """
{
  __type(name: "Mutation") {
    fields {
      name
      args { name type { kind name ofType { kind name ofType { kind name } } } }
    }
  }
}
"""
data = client.execute(INTROSPECT)
fields = data["__type"]["fields"]
for f in fields:
    if f["name"] == "metaobjectUpsert":
        print("metaobjectUpsert args:")
        for a in f["args"]:
            print("  ", a["name"], ":", json.dumps(a["type"]))

HANDLE = """
{
  __type(name: "MetaobjectHandleInput") {
    inputFields { name type { kind name ofType { kind name } } }
  }
}
"""
data2 = client.execute(HANDLE)
print("MetaobjectHandleInput fields:")
for f in (data2.get("__type") or {}).get("inputFields", []):
    print("  ", f["name"], ":", json.dumps(f["type"]))

FIELDS_IN = """
{
  __type(name: "MetaobjectFieldInput") {
    inputFields { name type { kind name ofType { kind name } } }
  }
}
"""
data3 = client.execute(FIELDS_IN)
print("MetaobjectFieldInput fields:")
for f in (data3.get("__type") or {}).get("inputFields", []):
    print("  ", f["name"], ":", json.dumps(f["type"]))

DEF_IN = """
{
  __type(name: "MetaobjectUpsertPayload") {
    fields { name type { kind name ofType { kind name } } }
  }
}
"""
data4 = client.execute(DEF_IN)
print("MetaobjectUpsertPayload fields:")
for f in (data4.get("__type") or {}).get("fields", []):
    print("  ", f["name"], ":", json.dumps(f["type"]))

META_OBJ = """
{
  __type(name: "Metaobject") {
    fields { name }
  }
}
"""
data5 = client.execute(META_OBJ)
print("Metaobject fields:", [f["name"] for f in (data5.get("__type") or {}).get("fields", [])])
