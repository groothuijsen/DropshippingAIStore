"""Tests for T-117: the store_build job (12 §5/§7, F15-10, F15-15).

Covers: limit reservation in one transaction, collections created
unpublished + ManagedResource bookkeeping, child jobs (standard pages,
home, one PDP per selected product), menu mosaiq-main created LAST,
idempotency on re-run, step retry with last_error, plan-limit failure,
and the build status screen with retry actions.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import Client

from apps.core.models import Shop
from apps.generator.models import (
    BlueprintStatus,
    GenerationJob,
    JobKind,
    JobStatus,
    ManagedResource,
    Page,
    StoreBlueprint,
)

G1 = "gid://shopify/Product/111"
G2 = "gid://shopify/Product/222"


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t117-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t117-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        onboarding_step="building",
        onboarding_route="zero",
    )


def _bp(shop: Shop, **overrides) -> StoreBlueprint:
    defaults = {
        "shop":shop,
        "status":BlueprintStatus.BUILDING,
        "onboarding_route":"zero",
        "brand_name":"Helderz",
        "description":"Weighted blankets for better sleep.",
        "markets":["NL"],
        "content_locales":["nl"],
        "brand_proposal":{"style_preset": "soft", "tagline": "Slaap beter."},
        "selected_product_gids":[G1, G2],
        "store_structure":{
            "collections": [{"title": "Alles", "description": "d", "product_gids": [G1, G2]}],
            "menu": [
                {"title": "Home", "target": "frontpage", "ref": None},
                {"title": "Alles", "target": "collection", "ref": "Alles"},
                {"title": "Verzending", "target": "page", "ref": "shipping"},
                {"title": "Retour", "target": "page", "ref": "returns"},
            ],
            "pages": ["faq", "shipping", "returns"],
        },
        "standard_pages":{
            "faq": {
                "title": "Veelgestelde vragen",
                "sections": [
                    {"type": "rich_text", "heading": "", "body": "Intro."},
                    {"type": "faq", "items": [{"question": "Q?", "answer": "A."}]},
                ],
                "warnings": [],
            },
            "shipping": {
                "title": "Verzending",
                "sections": [
                    {"type": "rich_text", "heading": "", "body": "Intro."},
                    {"type": "rich_text", "heading": "Levertijden", "body": "missing"},
                    {"type": "faq", "items": [{"question": "Q?", "answer": "A."}]},
                ],
                "warnings": [],
            },
            "returns": {
                "title": "Retourneren",
                "sections": [{"type": "rich_text", "heading": "", "body": "Intro."}],
                "warnings": [],
            },
        },
    }
    defaults.update(overrides)
    return StoreBlueprint.objects.create(**defaults)


def _client_mock():
    """A GraphQL mock that answers by query shape (fixture-like responses)."""
    client = MagicMock()

    def execute(query, variables=None):
        variables = variables or {}
        if "collectionCreate" in query:
            col = variables.get("collection", {})
            handle = col.get("handle", "c")
            return {
                "collectionCreate": {
                    "collection": {
                        "id": f"gid://shopify/Collection/{handle}",
                        "title": col.get("title", ""),
                        "handle": handle,
                        "userErrors": [],
                    },
                    "userErrors": [],
                }
            }
        if "menuCreate" in query:
            return {
                "menuCreate": {
                    "menu": {"id": "gid://shopify/Menu/900", "handle": "mosaiq-main"},
                    "userErrors": [],
                }
            }
        if "menuUpdate" in query:
            return {
                "menuUpdate": {
                    "menu": {"id": variables.get("id"), "handle": "mosaiq-main"},
                    "userErrors": [],
                }
            }
        if "pageCreate" in query:
            page = variables.get("page", {})
            return {
                "pageCreate": {
                    "page": {"id": f"gid://shopify/Page/{page.get('handle', 'p')}", "handle": page.get("handle", "p")},
                    "userErrors": [],
                }
            }
        if "metaobjectUpsert" in query:
            return {"metaobjectUpsert": {"metaobject": {"id": "gid://shopify/Metaobject/1"}, "userErrors": []}}
        if "metafieldsSet" in query:
            return {"metafieldsSet": {"metafields": [{"id": "gid://shopify/Metafield/1"}], "userErrors": []}}
        if "productGet" in query or "productBy" in query:
            return {
                "data": {
                    "product": {
                        "id": variables.get("id", G1),
                        "title": "Weighted blanket",
                        "descriptionHtml": "<p>Soft blanket.</p>",
                        "status": "ACTIVE",
                        "productType": "Blanket",
                        "vendor": "Helderz",
                        "options": [],
                        "variants": {
                            "nodes": [
                                {
                                    "id": "gid://shopify/ProductVariant/1",
                                    "title": "Default",
                                    "price": "59.00",
                                    "sku": None,
                                    "barcode": None,
                                    "inventoryQuantity": 5,
                                    "selectedOptions": [],
                                    "image": None,
                                }
                            ]
                        },
                        "media": {"nodes": []},
                        "metafields": {"nodes": []},
                    }
                }
            }
        return {}

    client.execute.side_effect = execute
    return client


def _run_build(shop: Shop, bp: StoreBlueprint, client=None, child_runner=None):
    from apps.generator.tasks import run_store_build

    client = client or _client_mock()
    with (
        patch("apps.generator.store_build._get_client", return_value=client),
        patch("apps.generator.tasks.run_store_build_child") as child_task,
    ):
        child_runner = child_runner or (lambda job_id: None)
        # The task is invoked via .delay(...), so the runner hooks .delay
        child_task.delay.side_effect = child_runner
        run_store_build(str(bp.id))
    bp.refresh_from_db()
    return bp, client, child_task


class TestManagedResourceAndModel:
    def test_managed_resource_unique_per_shop(self, db, shop):
        bp = _bp(shop)
        ManagedResource.objects.create(shop=shop, blueprint=bp, kind="collection", gid="gid://shopify/Collection/1", handle="alles")
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            ManagedResource.objects.create(shop=shop, blueprint=bp, kind="page", gid="gid://shopify/Collection/1", handle="x")

    def test_blueprint_has_build_fields(self, db, shop):
        bp = _bp(shop)
        assert bp.build_job is None
        assert bp.store_limit_reserved_at is None


class TestStoreBuildTask:
    def test_creates_job_idempotently(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        jobs = GenerationJob.objects.filter(shop=shop, kind=JobKind.STORE)
        assert jobs.count() == 1
        job = jobs.first()
        assert job.idempotency_key == f"store-build-{bp.id}"
        assert bp.build_job_id == job.id

    def test_reserves_limits_once(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1, G2])
        # 2 PDPs → store_generations = 1 + (2-1) = 2, ai_images = 2
        bp, _, _ = _run_build(shop, bp)
        from apps.billing.models import UsageCounter

        counter = UsageCounter.objects.filter(shop=shop).first()
        assert counter is not None
        assert counter.reserved_store_generations == 2
        assert counter.reserved_ai_images == 2
        assert bp.store_limit_reserved_at is not None

    def test_collections_created_unpublished_with_managed_resource(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, client, _ = _run_build(shop, bp)
        mrs = ManagedResource.objects.filter(shop=shop, kind="collection")
        assert mrs.count() == 1
        mr = mrs.first()
        assert mr.handle == "alles"
        assert mr.gid.startswith("gid://shopify/Collection/")
        collection_calls = [
            c for c in client.execute.call_args_list if "collectionCreate" in c.args[0]
        ]
        assert len(collection_calls) == 1
        sources = collection_calls[0].kwargs["variables"]["collection"]["sources"]
        assert sources[0]["source"]["inclusion"]["selections"] == [{"productId": G1}, {"productId": G2}]

    def test_children_created(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1, G2])
        bp, _, child_task = _run_build(shop, bp)
        job = bp.build_job
        children = GenerationJob.objects.filter(parent=job)
        # 3 standard pages + home + 2 PDPs
        assert children.filter(kind=JobKind.PAGE).count() == 6
        assert children.filter(page_type="pdp").count() == 2
        assert children.filter(page_type="home").count() == 1
        for page_type in ("faq", "shipping", "returns", "home"):
            assert children.filter(page_type=page_type).count() == 1
        # children enqueued
        assert child_task.delay.call_count == 6

    def test_standard_page_children_skip_product_pipeline(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        shipping = GenerationJob.objects.filter(parent=bp.build_job, page_type="shipping").first()
        statuses = dict(shipping.steps.values_list("name", "status"))
        assert statuses["layout"] == "pending"
        assert statuses["publish"] == "pending"
        for name in ("import", "research", "copy", "images", "compliance_check"):
            assert statuses[name] == "skipped", name

    def test_standard_pages_get_local_page_rows(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        pages = Page.objects.filter(page_type="faq")
        assert pages.count() == 1
        page = pages.first()
        assert page.content_locale == "nl"
        sections = page.sections["nl"]["sections"]
        assert sections[0]["type"] == "rich_text"
        assert page.title == "Veelgestelde vragen"

    def test_home_page_from_brand(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        home = Page.objects.filter(page_type="home").first()
        assert home is not None
        body = str(home.sections)
        assert "Helderz" in body

    def test_pdp_children_have_full_step_chain(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        pdp = GenerationJob.objects.filter(parent=bp.build_job, page_type="pdp").first()
        steps = list(pdp.steps.values_list("name", flat=True))
        assert steps == ["import", "research", "copy", "images", "compliance_check", "layout", "publish"]
        assert pdp.input["usage_reserved"] is True

    def test_rerun_does_not_duplicate(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, client1, _ = _run_build(shop, bp)
        # Simulate a re-run (e.g. retry after a later failure)
        bp.build_job.status = JobStatus.FAILED
        bp.build_job.save(update_fields=["status"])
        bp, client2, _ = _run_build(shop, bp)
        new_collection_calls = [
            c for c in client2.execute.call_args_list if "collectionCreate" in c.args[0]
        ]
        assert new_collection_calls == []
        assert ManagedResource.objects.filter(shop=shop, kind="collection").count() == 1

    def test_plan_limit_reached(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        from apps.billing.limits import LimitResult

        with patch("apps.billing.limits.reserve", return_value=LimitResult(allowed=False, remaining=0, limit=1, message="Upgrade your plan.")):
            bp, _, _ = _run_build(shop, bp)
        job = bp.build_job
        assert job.status == JobStatus.FAILED
        assert job.error_code == "PLAN_LIMIT_REACHED"
        assert "Upgrade" in job.error_message

    def test_no_products_fails(self, db, shop):
        bp = _bp(shop, selected_product_gids=[])
        bp, _, _ = _run_build(shop, bp)
        job = GenerationJob.objects.filter(shop=shop, kind=JobKind.STORE).first()
        assert job.status == JobStatus.FAILED
        assert job.error_code == "BLUEPRINT_NO_PRODUCTS"

    def test_collection_failure_keeps_last_error(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        client = _client_mock()
        client.execute.side_effect = RuntimeError("boom")

        with (
            patch("apps.generator.store_build._get_client", return_value=client),
            patch("apps.generator.tasks.run_store_build_child"),
        ):
            from apps.generator.tasks import run_store_build

            run_store_build(str(bp.id))
        bp.refresh_from_db()
        step = bp.build_job.steps.get(name="research")
        assert step.status == "failed"
        assert "boom" in step.output["last_error"]

    def test_retry_resumes_same_job(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        client = _client_mock()
        calls = {"n": 0}

        fallback = _client_mock()

        def flaky(query, variables=None):
            calls["n"] += 1
            if "collectionCreate" in query and calls["n"] == 1:
                raise RuntimeError("transient")
            return fallback.execute(query, variables)

        client.execute.side_effect = flaky
        with (
            patch("apps.generator.store_build._get_client", return_value=client),
            patch("apps.generator.tasks.run_store_build_child"),
        ):
            from apps.generator.tasks import run_store_build

            run_store_build(str(bp.id))
        bp.refresh_from_db()
        first_job_id = bp.build_job_id
        assert bp.build_job.status == JobStatus.FAILED

        with (
            patch("apps.generator.store_build._get_client", return_value=_client_mock()),
            patch("apps.generator.tasks.run_store_build_child"),
        ):
            run_store_build(str(bp.id))
        bp.refresh_from_db()
        assert bp.build_job_id == first_job_id
        assert GenerationJob.objects.filter(shop=shop, kind=JobKind.STORE).count() == 1


class TestMenuLast:
    def test_menu_created_after_children(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        order: list[str] = []

        client = _client_mock()
        base_execute = client.execute.side_effect

        def tracking(query, variables=None):
            if "menuCreate" in query:
                order.append("menu")
                # All page ManagedResources must exist before the menu
                assert ManagedResource.objects.filter(shop=shop, kind="page").count() >= 4
            if "collectionCreate" in query:
                order.append("collection")
            return base_execute(query, variables)

        client.execute.side_effect = tracking
        bp, _, _ = _run_build(shop, bp, client=client, child_runner=lambda job_id: _finish_child(job_id))
        assert order[0] == "collection"
        assert order[-1] == "menu"
        mr = ManagedResource.objects.filter(shop=shop, kind="menu").first()
        assert mr is not None
        assert mr.handle == "mosaiq-main"
        assert bp.build_job.status == JobStatus.SUCCEEDED

    def test_menu_items_shape(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        client = _client_mock()
        captured: dict = {}

        base = client.execute.side_effect

        def capture(query, variables=None):
            if "menuCreate" in query:
                captured.update(variables)
            return base(query, variables)

        client.execute.side_effect = capture
        bp, _, _ = _run_build(shop, bp, client=client, child_runner=lambda job_id: _finish_child(job_id))
        items = captured["items"]
        types = [i["type"] for i in items]
        assert types[0] == "FRONTPAGE"
        assert "COLLECTION" in types
        assert "PAGE" in types
        collection_item = next(i for i in items if i["type"] == "COLLECTION")
        assert collection_item["resourceId"].startswith("gid://shopify/Collection/")

    def test_menu_updated_on_rerun(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp, child_runner=lambda job_id: _finish_child(job_id))
        assert bp.build_job.status == JobStatus.SUCCEEDED
        client = _client_mock()
        captured: dict = {}
        base = client.execute.side_effect

        def capture(query, variables=None):
            if "menuUpdate" in query:
                captured.update(variables)
            return base(query, variables)

        client.execute.side_effect = capture
        # Simulate an interrupted resume: parent back to running, menu pending
        bp.build_job.status = JobStatus.RUNNING
        bp.build_job.save(update_fields=["status"])
        menu_step = bp.build_job.steps.get(name="publish")
        menu_step.status = "pending"
        menu_step.save(update_fields=["status"])
        with (
            patch("apps.generator.store_build._get_client", return_value=client),
            patch("apps.generator.tasks.run_store_build_child"),
        ):
            from apps.generator.tasks import run_store_build

            run_store_build(str(bp.id))
        assert captured.get("id", "").startswith("gid://shopify/Menu/")


def _finish_child(job_id: str) -> None:
    """Child runner: simulate a successful publish + advance the parent."""
    from apps.generator.store_build import advance_store_build, register_page_resources

    job = GenerationJob.objects.get(id=job_id)
    job.status = JobStatus.SUCCEEDED
    job.save(update_fields=["status"])
    for step in job.steps.all():
        step.status = "succeeded"
        step.save(update_fields=["status"])
    # Simulate what run_publish stores: the Shopify page GID on the Page row
    for page in Page.objects.filter(job=job):
        page.shopify_page_gid = f"gid://shopify/Page/sim-{str(page.id)[:8]}"
        page.save(update_fields=["shopify_page_gid"])
    blueprint_id = (job.input or {}).get("blueprint_id")
    if blueprint_id:
        register_page_resources(blueprint_id)
    advance_store_build(job.parent)


class TestChildAdvance:
    def test_needs_input_child_blocks_menu(self, db, shop):
        """A needs_input child is NOT terminal: the menu step must wait
        (found live — the first build published the menu while the PDP
        child still hung in needs_input)."""
        from apps.generator.store_build import children_state

        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        pdp = GenerationJob.objects.filter(parent=bp.build_job, page_type="pdp").first()
        for child in GenerationJob.objects.filter(parent=bp.build_job):
            child.status = JobStatus.SUCCEEDED
            child.save(update_fields=["status"])
        pdp.status = JobStatus.NEEDS_INPUT
        pdp.save(update_fields=["status"])
        state = children_state(bp.build_job)
        assert state["running"] == 1
        from apps.generator.store_build import advance_store_build

        menu_step = bp.build_job.steps.get(name="publish")
        menu_step.status = "pending"
        menu_step.save(update_fields=["status"])
        with patch("apps.generator.store_build._get_client"):
            advance_store_build(bp.build_job)
        menu_step.refresh_from_db()
        assert menu_step.status == "pending"

    def test_failed_child_keeps_parent_running(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])

        def failing_child(job_id: str) -> None:
            job = GenerationJob.objects.get(id=job_id)
            job.status = JobStatus.FAILED
            job.error_code = "UNKNOWN_ERROR"
            job.error_message = "step blew up"
            job.save(update_fields=["status", "error_code", "error_message"])

        bp, _, _ = _run_build(shop, bp, child_runner=failing_child)
        bp.build_job.refresh_from_db()
        assert bp.build_job.status == JobStatus.RUNNING
        # no menu was created
        assert not ManagedResource.objects.filter(shop=shop, kind="menu").exists()

    def test_retry_child_enqueues(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        child = GenerationJob.objects.filter(parent=bp.build_job, page_type="pdp").first()
        token = TestStatusScreen()._auth(shop)
        with patch("apps.generator.tasks.run_store_build_child") as task:
            Client().post(
                f"/app/start/?id_token={token}",
                data={"action": "retry_child", "job_id": str(child.id)},
            )
        task.delay.assert_called_once_with(str(child.id))


class TestAutoAngle:
    def test_needs_input_child_gets_auto_angle(self, db, shop):
        """F15 store builds have no angle screen: the child auto-selects
        an angle and resumes instead of hanging in needs_input."""
        from apps.generator.models import JobStep, StepStatus
        from apps.generator.tasks import run_store_build_child

        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        pdp = GenerationJob.objects.filter(parent=bp.build_job, page_type="pdp").first()
        pdp.status = JobStatus.NEEDS_INPUT
        pdp.save(update_fields=["status"])
        research = JobStep.objects.get(job=pdp, name="research")
        research.status = StepStatus.SUCCEEDED
        research.output = {
            "angles": [
                {"id": "a1", "label": "Sleep better", "hook": "weighted blanket for deep sleep"},
                {"id": "a2", "label": "Gift idea", "hook": "a lovely gift"},
            ]
        }
        research.save(update_fields=["status", "output"])

        with (
            patch("apps.generator.tasks.execute_job") as ej,
            patch("apps.generator.store_build.register_page_resources"),
            patch("apps.generator.store_build.advance_store_build"),
        ):
            ej.return_value = {"status": "needs_input"}
            run_store_build_child(str(pdp.id))
        pdp.refresh_from_db()
        assert pdp.input.get("angle_id") in {"a1", "a2"}
        research.refresh_from_db()
        assert research.output.get("chosen_angle", {}).get("id") == pdp.input["angle_id"]

    def test_auto_angle_prefers_keyword_match(self, db, shop):
        from apps.generator.tasks import _auto_angle

        bp = _bp(shop, description="Weighted blankets for better sleep.", audience="tired parents")
        bp.save()
        job = GenerationJob(shop=shop, kind=JobKind.PAGE, content_locale="nl", input={"blueprint_id": str(bp.id)}, idempotency_key="x")
        angles = [
            {"id": "a1", "label": "Gift", "hook": "perfect present"},
            {"id": "a2", "label": "Sleep", "hook": "weighted blanket deep sleep"},
        ]
        assert _auto_angle(job, angles) == "a2"


class TestStatusScreen:
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

    def test_panel_lists_steps_and_children(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        token = self._auth(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        text = resp.content.decode()
        assert resp.status_code == 200
        assert "Build" in text
        assert "shipping" in text
        assert "home" in text

    def test_panel_shows_build_button_before_start(self, db, shop):
        _bp(shop, selected_product_gids=[G1])
        token = self._auth(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        text = resp.content.decode()
        assert "Build my store" in text or "build_store" in text

    def test_retry_build_action(self, db, shop):
        bp = _bp(shop, selected_product_gids=[G1])
        bp, _, _ = _run_build(shop, bp)
        bp.build_job.status = JobStatus.FAILED
        bp.build_job.save(update_fields=["status"])
        token = self._auth(shop)
        with patch("apps.generator.start_views.run_store_build") as task:
            resp = Client().post(
                f"/app/start/?id_token={token}",
                data={"action": "retry_build"},
            )
        task.delay.assert_called_once()
        assert resp.status_code == 302
