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
        job, created = create_pdp_job(shop, "gid://shopify/Product/123", "nl")
        assert created is True
        assert job.kind == JobKind.PAGE
        assert job.page_type == PageType.PDP
        assert job.status == JobStatus.QUEUED
        assert job.content_locale == "nl"
        assert job.input["product_gid"] == "gid://shopify/Product/123"
        steps = [s.name for s in job.steps.all()]
        assert steps == ["import", "research", "copy", "images", "compliance_check", "layout", "publish"]

    def test_reuses_inflight_job_for_same_product(self, shop):
        job1, _ = create_pdp_job(shop, "gid://shopify/Product/123", "nl")
        job2, created2 = create_pdp_job(shop, "gid://shopify/Product/123", "nl")
        assert created2 is False
        assert job1.id == job2.id
        assert GenerationJob.objects.filter(shop=shop).count() == 1

    def test_creates_second_job_for_other_product(self, shop):
        create_pdp_job(shop, "gid://shopify/Product/123", "nl")
        job2, created2 = create_pdp_job(shop, "gid://shopify/Product/456", "nl")
        assert created2 is True
        assert GenerationJob.objects.filter(shop=shop).count() == 2


class TestProductStartView:
    def test_get_renders_picker_with_products(self, shop, monkeypatch):
        monkeypatch.setattr(
            "apps.generator.product_start_views._fetch_products",
            lambda s: [{"id": "gid://shopify/Product/1", "title": "Test product", "status": "ACTIVE", "vendor": "X", "featuredMedia": None}],
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
            {"product_gid": "gid://shopify/Product/999", "locale": "en", "niche_hint": "test"},
        )
        assert resp.status_code == 302
        assert "/app/jobs/" in resp["Location"]
        assert GenerationJob.objects.filter(shop=shop).count() == 1


class TestJobStatusView:
    def test_status_shows_steps(self, shop):
        job, _ = create_pdp_job(shop, "gid://shopify/Product/123", "nl")
        html = Client().get(f"/app/jobs/{job.id}/").content.decode()
        assert "Import" in html and "Research" in html and "Publish" in html

    def test_unknown_job_blocked(self, shop):
        resp = Client().get("/app/jobs/00000000-0000-0000-0000-000000000000/")
        assert resp.status_code == 403

    def test_dashboard_has_card(self, shop):
        html = Client().get("/app/").content.decode()
        assert "/app/start/product/" in html
