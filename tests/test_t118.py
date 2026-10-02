"""Tests for T-118: menu placement, Publish store (go-live) + Undo (F15-12..14)."""

from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from apps.core.models import AuditLog, Shop
from apps.generator.models import (
    BlueprintStatus,
    GenerationJob,
    ManagedResource,
    Page,
    PageStatus,
    StoreBlueprint,
)

G1 = "gid://shopify/Product/111"


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t118-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t118-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        onboarding_step="building",
        onboarding_route="zero",
    )


def _bp(shop: Shop, **overrides) -> StoreBlueprint:
    defaults = {
        "shop": shop,
        "status": BlueprintStatus.BUILDING,
        "onboarding_route": "zero",
        "brand_name": "Helderz",
        "selected_product_gids": [G1],
        "store_structure": {
            "collections": [{"title": "Alles", "description": "d", "product_gids": [G1]}],
            "menu": [],
            "pages": ["shipping", "returns"],
        },
        "standard_pages": {
            "shipping": {"title": "Verzending", "sections": [{"type": "rich_text", "body": "x"}], "warnings": []},
            "returns": {"title": "Retourneren", "sections": [{"type": "rich_text", "body": "y"}], "warnings": []},
        },
    }
    defaults.update(overrides)
    return StoreBlueprint.objects.create(**defaults)


def _built(shop: Shop, **overrides) -> StoreBlueprint:
    """Blueprint with a succeeded build: job, collection + menu + page MRs,
    local Pages (shipping live-able, returns blocked without business
    details), publication mocks ready."""
    from apps.generator.models import JobKind, JobStatus, StepStatus

    bp = _bp(shop, **overrides)
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
    for name in ("import", "research", "copy", "publish"):
        job.steps.create(name=name, status=StepStatus.SUCCEEDED)

    ManagedResource.objects.create(
        shop=shop, blueprint=bp, kind="collection", gid="gid://shopify/Collection/77", handle="alles", title="Alles"
    )
    ManagedResource.objects.create(
        shop=shop, blueprint=bp, kind="menu", gid="gid://shopify/Menu/88", handle="mosaiq-main", title="Mosaiq"
    )

    shipping_job = GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        parent=job,
        page_type="shipping",
        content_locale="nl",
        input={"blueprint_id": str(bp.id)},
        status=JobStatus.SUCCEEDED,
        idempotency_key=f"bp-page-{bp.id}-shipping",
    )
    shipping = Page.objects.create(
        shop=shop,
        job=shipping_job,
        page_type="shipping",
        content_locale="nl",
        title="Verzending",
        sections={"nl": {"sections": [{"type": "rich_text", "body": "x"}]}},
        shopify_page_gid="gid://shopify/Page/11",
        status=PageStatus.DRAFT,
    )
    ManagedResource.objects.create(
        shop=shop, blueprint=bp, kind="page", gid=shipping.shopify_page_gid, handle="mq-shipping-1-nl", title="Verzending"
    )
    returns_job = GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        parent=job,
        page_type="returns",
        content_locale="nl",
        input={"blueprint_id": str(bp.id)},
        status=JobStatus.SUCCEEDED,
        idempotency_key=f"bp-page-{bp.id}-returns",
    )
    returns = Page.objects.create(
        shop=shop,
        job=returns_job,
        page_type="returns",
        content_locale="nl",
        title="Retourneren",
        sections={"nl": {"sections": [{"type": "rich_text", "body": "y"}]}},
        shopify_page_gid="gid://shopify/Page/12",
        status=PageStatus.DRAFT,
    )
    ManagedResource.objects.create(
        shop=shop, blueprint=bp, kind="page", gid=returns.shopify_page_gid, handle="mq-returns-1-nl", title="Retourneren"
    )
    return bp


def _client_mock():
    client = MagicMock()

    def execute(query, variables=None):
        variables = variables or {}
        if "publications" in query:
            return {
                "publications": {
                    "nodes": [
                        {"id": "gid://shopify/Publication/1", "name": "Point of Sale"},
                        {"id": "gid://shopify/Publication/2", "name": "Online Store"},
                    ]
                }
            }
        if "publishablePublish" in query:
            return {"publishablePublish": {"userErrors": []}}
        if "collectionDelete" in query:
            return {"collectionDelete": {"deletedCollectionId": variables.get("input", {}).get("id"), "userErrors": []}}
        if "menuDelete" in query:
            return {"menuDelete": {"deletedMenuId": variables.get("id"), "userErrors": []}}
        if "pageDelete" in query:
            return {"pageDelete": {"deletedPageId": variables.get("id"), "userErrors": []}}
        if "pagePublish" in query:
            return {"pagePublish": {"page": {"id": "gid://shopify/Page/11"}, "userErrors": []}}
        if "metaobjectUpsert" in query:
            return {"metaobjectUpsert": {"metaobject": {"id": "gid://shopify/Metaobject/1"}, "userErrors": []}}
        if "metaobjectGet" in query or "metaobject(id" in query:
            return {"metaobject": {"id": "gid://shopify/Metaobject/1", "fields": [{"key": "sections", "value": "{}"}]}}
        return {}

    client.execute.side_effect = execute
    return client


class TestPublishCollections:
    def test_publishes_each_collection_to_online_store(self, db, shop):
        from apps.generator.store_go_live import publish_collections

        bp = _built(shop)
        client = _client_mock()
        published = publish_collections(client, bp)
        calls = [c for c in client.execute.call_args_list if "publishablePublish" in c.args[0]]
        assert len(calls) == 1
        assert calls[0].kwargs["variables"]["id"] == "gid://shopify/Collection/77"
        assert calls[0].kwargs["variables"]["input"] == [{"publicationId": "gid://shopify/Publication/2"}]
        assert published == ["gid://shopify/Collection/77"]

    def test_user_errors_raise(self, db, shop):
        from apps.generator.store_go_live import publish_collections

        bp = _built(shop)
        client = _client_mock()

        def failing(query, variables=None):
            if "publishablePublish" in query:
                return {"publishablePublish": {"userErrors": [{"field": "input", "message": "boom"}]}}
            return _client_mock().execute(query, variables)

        client.execute.side_effect = failing
        with pytest.raises(RuntimeError, match="boom"):
            publish_collections(client, bp)


class TestPublishStore:
    def _run(self, bp, business_details=False):
        from apps.core.models import BusinessDetails
        from apps.generator.tasks import run_store_publish

        if business_details:
            BusinessDetails.objects.create(
                shop=bp.shop,
                legal_name="Helderz B.V.",
                street="Dorpsstraat 1",
                postal_code="6100AB",
                city="Venlo",
                country_code="NL",
                return_address_same=True,
            )
        client = _client_mock()
        with (
            patch("apps.generator.store_go_live._get_client", return_value=client),
            patch("apps.generator.go_live._get_client", return_value=client),
        ):
            run_store_publish(str(bp.id))
        bp.refresh_from_db()
        return bp, client

    def test_shipping_goes_live_and_returns_blocked(self, db, shop):
        bp, _ = self._run(_built(shop))
        result = bp.publish_result
        assert "shipping" in result["published_pages"]
        assert result["published_pages"]["shipping"]["status"] == "live"
        blocked = {b["page_type"]: b for b in result["blocked_pages"]}
        assert "returns" in blocked
        reasons = str(blocked["returns"]["reasons"])
        assert "BUSINESS_DETAILS_MISSING" in reasons
        shipping = Page.objects.get(page_type="shipping", shop=shop)
        returns = Page.objects.get(page_type="returns", shop=shop)
        assert shipping.status == PageStatus.LIVE
        assert returns.status == PageStatus.DRAFT

    def test_returns_live_with_business_details(self, db, shop):
        bp, _ = self._run(_built(shop), business_details=True)
        result = bp.publish_result
        assert "returns" in result["published_pages"]

    def test_collections_published_together(self, db, shop):
        bp, client = self._run(_built(shop))
        calls = [c for c in client.execute.call_args_list if "publishablePublish" in c.args[0]]
        assert len(calls) == 1  # the one blueprint collection
        assert bp.publish_result["collections_published"] == ["gid://shopify/Collection/77"]

    def test_audit_log_written(self, db, shop):
        bp, _ = self._run(_built(shop))
        assert AuditLog.objects.filter(shop=shop, action="store_publish").exists()

    def test_skips_without_build(self, db, shop):
        from apps.generator.tasks import run_store_publish

        bp = _bp(shop)  # no build_job
        run_store_publish(str(bp.id))
        bp.refresh_from_db()
        assert bp.publish_result is None


class TestUndo:
    def test_refuses_when_live_pages_exist(self, db, shop):
        from apps.generator.tasks import run_undo_build

        bp = _built(shop)
        shipping = Page.objects.get(page_type="shipping", shop=shop)
        shipping.status = PageStatus.LIVE
        shipping.save(update_fields=["status"])
        client = _client_mock()
        with patch("apps.generator.store_go_live._get_client", return_value=client):
            result = run_undo_build(str(bp.id))
        assert result["blocked"]
        assert any("shipping" in str(b) for b in result["blocked"])
        # nothing was deleted
        deletes = [c for c in client.execute.call_args_list if "Delete" in c.args[0]]
        assert deletes == []
        assert ManagedResource.objects.filter(shop=shop, removed_at__isnull=True).count() == 4

    def test_deletes_collections_menu_and_draft_pages(self, db, shop):
        from apps.generator.tasks import run_undo_build

        bp = _built(shop)
        client = _client_mock()
        with patch("apps.generator.store_go_live._get_client", return_value=client):
            result = run_undo_build(str(bp.id))
        kinds = [c.args[0].split("mutation")[1].split("(")[0].strip() for c in client.execute.call_args_list]
        assert "CollectionDelete" in kinds
        assert "MenuDelete" in kinds
        assert kinds.count("PageDelete") == 2
        assert result["deleted"]["collections"] == 1
        assert result["deleted"]["menu"] == 1
        assert result["deleted"]["pages"] == 2
        # local state: pages archived, MRs removed
        assert not Page.objects.filter(shop=shop, status=PageStatus.DRAFT).exists()
        assert not ManagedResource.objects.filter(shop=shop, removed_at__isnull=True).exists()

    def test_products_and_brandkit_untouched(self, db, shop):
        from apps.generator.tasks import run_undo_build

        bp = _built(shop)
        client = _client_mock()
        with patch("apps.generator.store_go_live._get_client", return_value=client):
            run_undo_build(str(bp.id))
        deletes = [c.args[0] for c in client.execute.call_args_list if "Delete" in c.args[0]]
        assert not any("product" in q.lower() for q in deletes)

    def test_audit_log_per_deletion(self, db, shop):
        from apps.generator.tasks import run_undo_build

        bp = _built(shop)
        client = _client_mock()
        with patch("apps.generator.store_go_live._get_client", return_value=client):
            run_undo_build(str(bp.id))
        logs = AuditLog.objects.filter(shop=shop, action="store_undo")
        assert logs.count() == 4  # collection + menu + 2 pages


class TestMenuPlacement:
    def _auth(self, shop: Shop) -> str:
        import jwt as pyjwt
        from django.conf import settings

        return pyjwt.encode(
            {
                "iss": f"https://{shop.domain}/admin",
                "dest": f"https://{shop.domain}",
                "aud": settings.SHOPIFY_API_KEY,
                "sub": "1",
                "exp": 9999999999,
                "nbf": 1,
            },
            settings.SHOPIFY_API_SECRET,
            algorithm="HS256",
        )

    def test_deep_link_contains_handle(self, db, shop):
        from apps.core.deep_links import get_menu_placement_link

        link = get_menu_placement_link(shop.domain, "mosaiq-main")
        assert "admin/themes/current/editor" in link
        assert "mosaiq-main" in link

    def test_done_checkbox_persists(self, db, shop):
        bp = _built(shop)
        token = self._auth(shop)
        resp = Client().post(
            f"/app/start/?id_token={token}",
            data={"action": "menu_placed", "value": "1"},
        )
        bp.refresh_from_db()
        assert resp.status_code == 302
        assert bp.menu_placed is True

    def test_publish_store_action_enqueues(self, db, shop):
        _built(shop)
        token = self._auth(shop)
        with patch("apps.generator.tasks.run_store_publish") as task:
            Client().post(
                f"/app/start/?id_token={token}",
                data={"action": "publish_store"},
            )
        task.delay.assert_called_once()

    def test_undo_action_enqueues(self, db, shop):
        _built(shop)
        token = self._auth(shop)
        with patch("apps.generator.tasks.run_undo_build") as task:
            Client().post(
                f"/app/start/?id_token={token}",
                data={"action": "undo_build"},
            )
        task.delay.assert_called_once()

    def test_panel_shows_publish_section(self, db, shop):
        from apps.core.models import BusinessDetails

        _built(shop)
        BusinessDetails.objects.create(
            shop=shop,
            legal_name="Helderz B.V.",
            street="Dorpsstraat 1",
            postal_code="6100AB",
            city="Venlo",
            country_code="NL",
            return_address_same=True,
        )
        token = self._auth(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        text = resp.content.decode()
        assert "Publish store" in text
        assert "mosaiq-main" in text
