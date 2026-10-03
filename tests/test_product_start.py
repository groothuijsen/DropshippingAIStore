import pytest
from django.test import Client

from apps.core.models import Shop
from apps.generator.models import GenerationJob, JobKind, JobStatus, PageType
from apps.generator.product_start_views import create_pdp_job

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    return Shop.objects.create(
        domain="start-test.myshopify.com",
        currency_code="EUR",
        status="active",
        access_token_encrypted=b"",
    )


@pytest.fixture(autouse=True)
def _no_middleware(settings):
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "SessionTokenMiddleware" not in m]


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    def fake_get_shop(request):
        return Shop.objects.filter(domain="start-test.myshopify.com").first()

    monkeypatch.setattr(
        "apps.generator.product_start_views._get_shop", fake_get_shop
    )


class TestCreatePdpJob:
    def test_creates_job_with_all_steps(self, shop):
        job, created = create_pdp_job(shop, locale="nl", product_gid="gid://shopify/Product/123")
        assert created is True
        assert job.kind == JobKind.PAGE
        assert job.page_type == PageType.PDP
        assert job.status == JobStatus.QUEUED
        assert job.content_locale == "nl"
        assert job.input["product_gid"] == "gid://shopify/Product/123"
        steps = [s.name for s in job.steps.all()]
        assert steps == ["import", "research", "copy", "images", "compliance_check", "layout", "publish"]

    def test_reuses_inflight_job_for_same_product(self, shop):
        job1, _ = create_pdp_job(shop, locale="nl", product_gid="gid://shopify/Product/123")
        job2, created2 = create_pdp_job(shop, locale="nl", product_gid="gid://shopify/Product/123")
        assert created2 is False
        assert job1.id == job2.id
        assert GenerationJob.objects.filter(shop=shop).count() == 1

    def test_creates_second_job_for_other_product(self, shop):
        create_pdp_job(shop, locale="nl", product_gid="gid://shopify/Product/123")
        job2, created2 = create_pdp_job(shop, locale="nl", product_gid="gid://shopify/Product/456")
        assert created2 is True
        assert GenerationJob.objects.filter(shop=shop).count() == 2


class TestProductStartView:
    def test_get_renders_picker_with_products(self, shop, monkeypatch):
        monkeypatch.setattr(
            "apps.generator.product_start_views._fetch_products",
            lambda s, **kw: ([{"id": "gid://shopify/Product/1", "title": "Test product", "status": "ACTIVE", "vendor": "X", "featuredMedia": None}], None),
        )
        monkeypatch.setattr(
            "apps.generator.product_start_views._source_labels",
            lambda s: {},
        )
        html = Client().get("/app/start/product/").content.decode()
        assert "Generate product page" in html and "Test product" in html

    def test_get_empty_state_without_products(self, shop):
        html = Client().get("/app/start/product/").content.decode()
        assert "No products found" in html

    def test_post_without_product_redirects(self, shop):
        resp = Client().post("/app/start/product/", {"locale": "nl"})
        assert resp.status_code == 302
        assert GenerationJob.objects.filter(shop=shop).count() == 0

    def test_post_creates_job_and_redirects_to_status(self, shop):
        resp = Client().post(
            "/app/start/product/",
            {"product_gid": "gid://shopify/Product/999", "locale": "en", "niche_hint": "test", "rights_confirmed": "1"},
        )
        assert resp.status_code == 302
        assert "/app/jobs/" in resp["Location"]
        assert GenerationJob.objects.filter(shop=shop).count() == 1


class TestJobStatusView:
    def test_status_shows_steps(self, shop):
        job, _ = create_pdp_job(shop, locale="nl", product_gid="gid://shopify/Product/123")
        html = Client().get(f"/app/jobs/{job.id}/").content.decode()
        assert "Import" in html and "Research" in html and "Publish" in html

    def test_unknown_job_blocked(self, shop):
        resp = Client().get("/app/jobs/00000000-0000-0000-0000-000000000000/")
        assert resp.status_code == 403

    def test_dashboard_has_card(self, shop):
        html = Client().get("/app/").content.decode()
        assert "/app/start/product/" in html


class TestThreeSources:
    def test_create_job_with_manual(self, shop):
        manual = {"title": "Test Widget", "description": "A widget that does things well.", "price": "19.99", "currency": "EUR", "specs": {}}
        job, created = create_pdp_job(shop, locale="en", manual=manual)
        assert created is True
        assert job.input["manual"]["title"] == "Test Widget"

    def test_create_job_with_source_url(self, shop):
        job, created = create_pdp_job(shop, locale="nl", source_url="https://example.com/product/1")
        assert created is True
        assert job.input["source_url"] == "https://example.com/product/1"

    def test_create_job_rejects_multiple_sources(self, shop):
        import pytest
        with pytest.raises(ValueError):
            create_pdp_job(shop, locale="en", product_gid="gid://shopify/Product/1", manual={"title": "x", "description": "y" * 20})

    def test_create_job_rejects_no_source(self, shop):
        import pytest
        with pytest.raises(ValueError):
            create_pdp_job(shop, locale="en")


class TestConfirmProductView:
    def test_confirm_requires_price(self, shop):
        job, _ = create_pdp_job(shop, locale="en", source_url="https://example.com/p")
        job.status = "needs_input"
        job.save()
        resp = Client().post(f"/app/jobs/{job.id}/confirm-product/", {"title": "Widget", "description": "A" * 25, "price": ""})
        assert resp.status_code == 302
        job.refresh_from_db()
        assert job.status == "needs_input"  # stays paused

    def test_confirm_resumes_with_manual(self, shop, monkeypatch):
        monkeypatch.setattr("apps.generator.product_start_views._enqueue", lambda job: None)
        job, _ = create_pdp_job(shop, locale="en", source_url="https://example.com/p")
        job.status = "needs_input"
        job.save()
        resp = Client().post(
            f"/app/jobs/{job.id}/confirm-product/",
            {"title": "Widget Pro", "description": "A great widget for daily use.", "price": "24.99", "currency": "EUR"},
        )
        assert resp.status_code == 302
        job.refresh_from_db()
        assert job.status == "queued"
        assert job.input["manual"]["title"] == "Widget Pro"
        assert job.input["manual"]["price"] == "24.99"
        import_step = job.steps.get(name="import")
        assert import_step.status == "pending"  # will re-run on manual product


class TestUrlFactsExtraction:
    def test_extract_url_facts_maps_facts_to_description(self, shop):
        """Bug fix: UrlFacts has title/facts:list/specs — description must be joined facts."""
        from apps.generator.import_step import _extract_url_facts

        class FakeFacts:
            title = "Test Product"
            facts = ["Material: steel", "Weight: 2kg", "Color: blue"]
            specs = {"material": "steel", "weight": "2kg"}

        import apps.ai.anthropic_client as ai_mod
        original = ai_mod.call_ai

        def fake_call_ai(**kwargs):
            return FakeFacts()

        ai_mod.call_ai = fake_call_ai
        try:
            result = _extract_url_facts(shop, "page text", "https://example.com")
        finally:
            ai_mod.call_ai = original

        assert result["title"] == "Test Product"
        assert "Material: steel" in result["description"]
        assert result["specs"]["material"] == "steel"


class TestImagesStepF01:
    """F01-7 skip gate + real upload wiring + layout copies gids onto Page.images."""

    def _job(self, shop, manual=None):
        if manual is None:
            manual = {"title": "Widget", "description": "A" * 25, "price": "10.00", "currency": "EUR"}
        job, _ = create_pdp_job(shop, locale="en", manual=manual)
        return job

    def test_images_skipped_without_own_media(self, shop):
        """F01-7: no product photo -> step returns None with merchant message."""
        from apps.generator.images_step import NO_OWN_MEDIA_MESSAGE, run_images

        job = self._job(shop)
        job.steps.filter(name="copy").update(status="succeeded", output={"sections": [{"type": "hero", "headline": "X", "subheadline": "Y"}]})
        step = job.steps.get(name="images")
        result = run_images(job, step)
        assert result is None
        step.refresh_from_db()
        assert step.output["skipped"] is True
        assert step.output["message"] == NO_OWN_MEDIA_MESSAGE

    def test_images_runs_with_manual_photo_and_uploads(self, shop, monkeypatch):
        """With a merchant photo the step generates + uploads to Shopify Files."""
        from apps.generator import images_step as imod
        from apps.generator.images_step import run_images

        job = self._job(shop, manual={"title": "Widget", "description": "A" * 25, "price": "10.00", "currency": "EUR", "photo_url": "https://cdn.example.com/photo.jpg"})
        job.steps.filter(name="copy").update(status="succeeded", output={"sections": [{"type": "hero", "headline": "Great Widget", "subheadline": "does things"}]})

        class FakeGen:
            success = True
            image_bytes = b"png-bytes" * 100

        monkeypatch.setattr(imod, "_generate_with_providers", lambda p, r: FakeGen())
        # C2PA fails in dev -> original bytes must be uploaded, not the empty temp file
        monkeypatch.setattr("apps.ai.c2pa.sign_image", lambda b, p: None)
        monkeypatch.setattr("apps.ai.image_upload.upload_image", lambda shop, b, filename, alt="": type("U", (), {"success": True, "file_gid": "gid://shopify/Asset/99", "error": ""})())

        step = job.steps.get(name="images")
        result = run_images(job, step)
        assert result is not None
        assert result["generated"] >= 1
        assert result["images"]["hero"]["gid"] == "gid://shopify/Asset/99"
        step.output = result  # execute_job normally persists this
        step.save(update_fields=["output"])

        # Layout copies the gids onto Page.images
        from apps.generator.layout_step import run_layout
        from apps.generator.models import Page, PageType

        page = Page.objects.create(
            job=job,
            shop=shop,
            title="Widget",
            content_locale="en",
            page_type=PageType.PDP,
            sections={"en": []},
            compliance_score=100,
        )
        layout_out = run_layout(job, job.steps.get(name="layout"))
        page.refresh_from_db()
        assert page.images["hero"]["gid"] == "gid://shopify/Asset/99"
        assert layout_out["page_id"] == str(page.id)


class TestConfirmPhotoUrl:
    def test_photo_url_stored_on_manual(self, shop):
        job, _ = create_pdp_job(shop, locale="en", source_url="https://example.com/p")
        job.status = "needs_input"
        job.save()
        Client().post(
            f"/app/jobs/{job.id}/confirm-product/",
            {"title": "Widget", "description": "A" * 25, "price": "19.00", "currency": "EUR", "photo_url": "https://cdn.example.com/mine.jpg"},
        )
        job.refresh_from_db()
        assert job.input["manual"]["photo_url"] == "https://cdn.example.com/mine.jpg"

    def test_bad_photo_url_rejected(self, shop):
        job, _ = create_pdp_job(shop, locale="en", source_url="https://example.com/p")
        job.status = "needs_input"
        job.save()
        Client().post(
            f"/app/jobs/{job.id}/confirm-product/",
            {"title": "Widget", "description": "A" * 25, "price": "19.00", "photo_url": "javascript:alert(1)"},
        )
        job.refresh_from_db()
        assert job.status == "needs_input"
        assert "photo_url" not in (job.input.get("manual") or {})


class TestMediaRightsF019:
    def test_requires_checkbox_for_unknown_source(self, shop):
        resp = Client().post("/app/start/product/", {"source": "existing", "product_gid": "gid://shopify/Product/777", "locale": "en"})
        assert resp.status_code == 302
        assert not GenerationJob.objects.filter(shop=shop).exists()

    def test_checkbox_creates_job_and_logs_audit(self, shop):
        from apps.core.models import AuditLog

        resp = Client().post("/app/start/product/", {"source": "existing", "product_gid": "gid://shopify/Product/777", "locale": "en", "rights_confirmed": "1"})
        assert resp.status_code == 302
        assert GenerationJob.objects.filter(shop=shop).count() == 1
        assert AuditLog.objects.filter(shop=shop, action="media_rights_confirmed").count() == 1

        # Second generation: confirmation remembered — no checkbox needed
        resp2 = Client().post("/app/start/product/", {"source": "existing", "product_gid": "gid://shopify/Product/777", "locale": "en"})
        assert resp2.status_code == 302
        assert GenerationJob.objects.filter(shop=shop).count() == 2
        assert AuditLog.objects.filter(shop=shop, action="media_rights_confirmed").count() == 1
