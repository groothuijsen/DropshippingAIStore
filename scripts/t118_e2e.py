"""T-118 live E2E — Publish store on the dev shop + API verification.

Does NOT run undo (that would delete the built dev store; undo is unit
tested and its deletions are exercised by the same GraphQL mutations the
E2E verifies read-side).
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.conf import settings  # noqa: E402

from apps.core.models import Shop  # noqa: E402
from apps.core.shopify_client import ShopifyGraphQLClient  # noqa: E402
from apps.core.tokens import decrypt_token  # noqa: E402
from apps.generator.models import ManagedResource, Page, StoreBlueprint  # noqa: E402
from apps.generator.tasks import run_store_publish  # noqa: E402

shop = Shop.objects.get(domain="mosaiq-pod.myshopify.com")
bp = StoreBlueprint.objects.filter(shop=shop).order_by("-created_at").first()
print("0) build_job:", bp.build_job_id is not None, "| menu_placed:", bp.menu_placed)

bp.publish_result = None
bp.save(update_fields=["publish_result", "updated_at"])
print("publish_result reset for a fresh run")
result = run_store_publish(str(bp.id))
print("1) publish result:", result)

client = ShopifyGraphQLClient(shop.domain, decrypt_token(shop.access_token_encrypted), settings.SHOPIFY_API_VERSION)

# Verify collections are published: read publication on each collection
for mr in ManagedResource.objects.filter(shop=shop, blueprint=bp, kind="collection"):
    data = client.execute(
        "query($id: ID!) { collection(id: $id) { id title publications(first: 5) { nodes { publication { id name } } } } }",
        variables={"id": mr.gid},
    )
    col = data.get("collection") or {}
    print("   collection", col.get("title"), "→ publications:", [(n.get("publication") or {}).get("name") for n in (col.get("publications") or {}).get("nodes", [])])

for page in Page.objects.filter(job__parent=bp.build_job):
    state = "unknown"
    if page.shopify_page_gid:
        data = client.execute(
            "query($id: ID!) { page(id: $id) { id handle isPublished } }",
            variables={"id": page.shopify_page_gid},
        )
        pg = data.get("page") or {}
        state = f"handle={pg.get('handle')} isPublished={pg.get('isPublished')}"
    print("   page", page.page_type, "→ status:", page.status, "|", state)

bp.refresh_from_db()
print("2) publish_result stored:", bool(bp.publish_result))
print("E2E DONE")
