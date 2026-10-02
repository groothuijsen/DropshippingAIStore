"""Phase close-out items (2026-10-02): F18-6 cut-off block + home MR gap."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.core.models import Shop
from apps.generator.models import (
    BlueprintStatus,
    GenerationJob,
    JobKind,
    JobStatus,
    ManagedResource,
    Page,
    PageStatus,
    StoreBlueprint,
)

BASE = Path(__file__).resolve().parent.parent
PRODUCT_GID = "gid://shopify/Product/222"


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t162-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t162",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
    )


class TestCutoffBlock:
    """F18-6: the 07 §3 cut-off notice block with its suppression rule."""

    def _block(self) -> str:
        return (BASE / "extensions/theme-blocks/blocks/mq-price.liquid").read_text()

    def test_block_renders_cutoff_notice(self):
        block = self._block()
        assert "price.cutoff_notice" in block
        assert "cutoff.time" in block

    def test_block_suppresses_when_max_days_exceeds_delivery_days(self):
        """max_days > ship_cutoff.delivery_days -> notice not rendered."""
        block = self._block()
        assert "cutoff.delivery_days" in block
        assert "delivery_range[1] > cutoff.delivery_days" in block
        assert "suppressed" in block

    def test_block_only_renders_on_cutoff_days_before_cutoff_time(self):
        block = self._block()
        assert "cutoff.days contains today_code" in block
        assert "now_hm < cutoff.time" in block

    def test_locales_have_cutoff_notice(self):
        for name in ("en.default.json", "nl.json", "de.json"):
            data = json.loads((BASE / "extensions/theme-blocks/locales" / name).read_text())
            assert data["price"]["cutoff_notice"], name
            assert "{{ time }}" in data["price"]["cutoff_notice"], name


class TestHomeManagedResource:
    """The home page publishes as a metaobject only — its MR must exist so
    Undo can remove it (T-117 lesson, 12 §2.3)."""

    def _built(self, shop: Shop) -> StoreBlueprint:
        bp = StoreBlueprint.objects.create(
            shop=shop,
            status=BlueprintStatus.BUILDING,
            onboarding_route="zero",
            brand_name="Helderz",
            selected_product_gids=[],
            store_structure={"collections": [], "menu": [], "pages": []},
            standard_pages={},
        )
        job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.STORE,
            idempotency_key=f"store-build-{bp.id}",
            content_locale="nl",
            input={"blueprint_id": str(bp.id)},
            status=JobStatus.SUCCEEDED,
        )
        bp.build_job = job
        bp.save(update_fields=["build_job", "updated_at"])
        return bp

    def test_metaobject_only_page_gets_mr(self, db, shop):
        from apps.generator.store_build import register_page_resources

        bp = self._built(shop)
        home_job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.PAGE,
            parent=bp.build_job,
            page_type="home",
            content_locale="nl",
            input={"blueprint_id": str(bp.id)},
            status=JobStatus.SUCCEEDED,
            idempotency_key=f"bp-home-{bp.id}",
        )
        Page.objects.create(
            shop=shop,
            job=home_job,
            page_type="home",
            content_locale="nl",
            title="Helderz",
            sections={"nl": {"sections": []}},
            status=PageStatus.LIVE,
            metaobject_gids={"nl": "gid://shopify/Metaobject/900"},
            metaobject_handles={"nl": "mq-home-abc-nl"},
        )
        register_page_resources(str(bp.id))
        mr = ManagedResource.objects.filter(shop=shop, gid="gid://shopify/Metaobject/900").first()
        assert mr is not None
        assert mr.kind == ManagedResource.Kind.PAGE
        assert mr.handle == "mq-home-abc-nl"

    def test_undo_deletes_metaobjects_via_metaobject_delete(self, db, shop):
        from apps.generator.store_go_live import undo_store_build

        bp = self._built(shop)
        # Draft shipping page (real Shopify page) + live home metaobject
        shipping_job = GenerationJob.objects.create(
            shop=shop,
            kind=JobKind.PAGE,
            parent=bp.build_job,
            page_type="shipping",
            content_locale="nl",
            input={"blueprint_id": str(bp.id)},
            status=JobStatus.SUCCEEDED,
            idempotency_key=f"bp-ship-{bp.id}",
        )
        Page.objects.create(
            shop=shop,
            job=shipping_job,
            page_type="shipping",
            content_locale="nl",
            title="Verzending",
            sections={"nl": {"sections": []}},
            status=PageStatus.DRAFT,
            shopify_page_gid="gid://shopify/Page/11",
        )
        ManagedResource.objects.create(
            shop=shop, blueprint=bp, kind="page", gid="gid://shopify/Page/11",
            handle="mq-shipping-1-nl", title="Verzending",
        )
        ManagedResource.objects.create(
            shop=shop, blueprint=bp, kind="page", gid="gid://shopify/Metaobject/900",
            handle="mq-home-abc-nl", title="Helderz",
        )
        ManagedResource.objects.create(
            shop=shop, blueprint=bp, kind="collection", gid="gid://shopify/Collection/77",
            handle="alles", title="Alles",
        )

        client = MagicMock()

        def execute(query, variables=None):
            variables = variables or {}
            if "metaobjectDelete" in query:
                return {"metaobjectDelete": {"deletedId": variables.get("id"), "userErrors": []}}
            if "pageDelete" in query:
                return {"pageDelete": {"deletedPageId": variables.get("id"), "userErrors": []}}
            if "collectionDelete" in query:
                return {"collectionDelete": {"deletedCollectionId": variables.get("input", {}).get("id"), "userErrors": []}}
            return {}

        client.execute.side_effect = execute
        with patch("apps.generator.store_go_live._get_client", return_value=client):
            result = undo_store_build(bp)
        kinds = [c.args[0] for c in client.execute.call_args_list]
        assert any("MetaobjectDelete" in q for q in kinds)
        assert any("PageDelete" in q for q in kinds)
        assert any("CollectionDelete" in q for q in kinds)
        assert result["deleted"]["pages"] == 2
        assert not ManagedResource.objects.filter(shop=shop, removed_at__isnull=True).exists()
