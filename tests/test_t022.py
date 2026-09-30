"""Tests for T-022: import step (existing, manual, URL) + product picker."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.generator.errors import ImportNotFound
from apps.generator.import_step import (
    _extract_text_from_html,
    _fetch_url,
    run_import_step,
)
from apps.generator.models import GenerationJob, JobKind, JobStatus
from apps.generator.picker import list_products
from apps.sources.models import ProductSource


@pytest.fixture
def shop(db):
    now = timezone.now()
    return Shop.objects.create(
        domain="test-store.myshopify.com",
        shopify_gid="gid://shopify/Shop/123",
        access_token_encrypted=encrypt_token("shpat_test_token"),
        access_token_expires_at=now + timedelta(hours=1),
        refresh_token_encrypted=encrypt_token("shpat_refresh_token"),
        refresh_token_expires_at=now + timedelta(days=90),
        currency_code="EUR",
        status=ShopStatus.ACTIVE,
    )


@pytest.fixture
def job(shop):
    return GenerationJob.objects.create(
        shop=shop,
        kind=JobKind.PAGE,
        page_type="pdp",
        content_locale="nl",
        input={},
        idempotency_key="test-import-001",
    )


# ── run_import_step: existing product ─────────────────────────────────────


@pytest.mark.django_db
class TestImportExistingProduct:
    @patch("apps.generator.import_tasks._get_client")
    def test_imports_by_gid(self, mock_get_client, shop, job):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "product": {
                "id": "gid://shopify/Product/1",
                "title": "Sleep Mask",
                "vendor": "Printify",
                "tags": "",
                "productType": "",
                "descriptionHtml": "",
                "status": "ACTIVE",
                "options": [],
                "variants": {
                    "nodes": [{"id": "v1", "title": "V", "price": "29.99", "compareAtPrice": None, "sku": "X1"}]
                },
                "media": {
                    "nodes": [{"id": "m1", "image": {"url": "https://cdn.example.com/img1.jpg", "altText": "Front"}}]
                },
                "metafields": {"nodes": []},
            }
        }

        job.input = {"product_gid": "gid://shopify/Product/1"}
        job.save(update_fields=["input"])

        result = run_import_step(job)

        assert result["product_gid"] == "gid://shopify/Product/1"
        assert result["title"] == "Sleep Mask"
        assert result["source_app"] == "printify"
        assert "title" in result["locked_fields"]

    @patch("apps.generator.import_tasks._get_client")
    def test_creates_product_source(self, mock_get_client, shop, job):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "product": {
                "id": "gid://shopify/Product/2",
                "title": "Test",
                "vendor": "",
                "tags": "",
                "productType": "",
                "descriptionHtml": "",
                "status": "ACTIVE",
                "options": [],
                "variants": {"nodes": []},
                "media": {"nodes": []},
                "metafields": {"nodes": []},
            }
        }

        job.input = {"product_gid": "gid://shopify/Product/2"}
        job.save(update_fields=["input"])

        run_import_step(job)

        assert ProductSource.objects.filter(shop=shop, product_gid="gid://shopify/Product/2").exists()


# ── run_import_step: manual product ───────────────────────────────────────


@pytest.mark.django_db
class TestImportManualProduct:
    @patch("apps.generator.import_tasks._get_client")
    def test_creates_manual_product(self, mock_get_client, shop, job):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {
            "productSet": {
                "product": {"id": "gid://shopify/Product/999", "title": "MP", "handle": "mp", "status": "DRAFT"},
                "userErrors": [],
            }
        }

        job.input = {
            "manual": {
                "title": "Manual Product",
                "description": "A" * 30,
                "specs": {},
                "price": "19.99",
            }
        }
        job.save(update_fields=["input"])

        result = run_import_step(job)

        assert result["product_gid"] == "gid://shopify/Product/999"
        assert result["source_app"] == "manual"

        ps = ProductSource.objects.get(shop=shop, product_gid="gid://shopify/Product/999")
        assert ps.created_by_mosaiq is True


# ── run_import_step: source URL ───────────────────────────────────────────


@pytest.mark.django_db
class TestImportFromUrl:
    @patch("apps.generator.import_step._fetch_url")
    @patch("apps.generator.import_step._extract_url_facts")
    def test_url_sets_needs_input(self, mock_facts, mock_fetch, shop, job):
        mock_fetch.return_value = "Some page text about a product"
        mock_facts.return_value = {
            "title": "Extracted Title",
            "description": "Extracted description",
            "specs": {"material": "cotton"},
        }

        job.input = {"source_url": "https://example.com/product"}
        job.save(update_fields=["input"])

        result = run_import_step(job)

        assert result["needs_input"] is True
        assert result["prefill"]["title"] == "Extracted Title"
        job.refresh_from_db()
        assert job.status == JobStatus.NEEDS_INPUT

    @patch("apps.generator.import_step._fetch_url", return_value=None)
    def test_blocked_url_sets_error(self, mock_fetch, shop, job):
        job.input = {"source_url": "https://blocked.example.com/product"}
        job.save(update_fields=["input"])

        result = run_import_step(job)

        assert result["needs_input"] is True
        assert result["error_code"] == "IMPORT_SOURCE_BLOCKED"
        job.refresh_from_db()
        assert job.status == JobStatus.NEEDS_INPUT
        assert job.error_code == "IMPORT_SOURCE_BLOCKED"


# ── run_import_step: no input ─────────────────────────────────────────────


@pytest.mark.django_db
class TestImportNoInput:
    def test_raises_import_not_found(self, shop, job):
        job.input = {}
        job.save(update_fields=["input"])

        with pytest.raises(ImportNotFound):
            run_import_step(job)


# ── URL fetching ──────────────────────────────────────────────────────────


class TestFetchUrl:
    @patch("httpx.Client")
    def test_successful_fetch(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<html><body><h1>Product</h1><p>Description here</p></body></html>"
        mock_client.get.return_value = mock_response

        with patch("urllib.robotparser.RobotFileParser") as mock_rp:
            mock_rp.return_value.can_fetch.return_value = True

            result = _fetch_url("https://example.com/product")

        assert result is not None
        assert "Product" in result
        assert "Description here" in result

    @patch("httpx.Client")
    def test_403_returns_none(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_client.get.return_value = mock_response

        with patch("urllib.robotparser.RobotFileParser") as mock_rp:
            mock_rp.return_value.can_fetch.return_value = True

            result = _fetch_url("https://example.com/blocked")

        assert result is None

    @patch("httpx.Client")
    def test_404_returns_none(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get.return_value = mock_response

        with patch("urllib.robotparser.RobotFileParser") as mock_rp:
            mock_rp.return_value.can_fetch.return_value = True

            result = _fetch_url("https://example.com/notfound")

        assert result is None

    @patch("httpx.Client")
    def test_robots_txt_disallows(self, mock_client_cls):
        with patch("urllib.robotparser.RobotFileParser") as mock_rp:
            mock_rp.return_value.can_fetch.return_value = False

            result = _fetch_url("https://example.com/blocked-by-robots")

        assert result is None
        mock_client_cls.assert_not_called()  # Should not even try to fetch


class TestExtractTextFromHtml:
    def test_strips_scripts_and_styles(self):
        html = "<html><head><script>var x=1;</script><style>.a{}</style></head><body><p>Hello</p></body></html>"
        text = _extract_text_from_html(html)
        assert "Hello" in text
        assert "var x" not in text
        assert ".a" not in text

    def test_strips_tags(self):
        html = "<html><body><h1>Title</h1><p>Body text</p></body></html>"
        text = _extract_text_from_html(html)
        assert "Title" in text
        assert "Body text" in text
        assert "<h1>" not in text

    def test_caps_at_10k(self):
        html = f"<html><body><p>{'x' * 20000}</p></body></html>"
        text = _extract_text_from_html(html)
        assert len(text) <= 10000


# ── Product picker tests ──────────────────────────────────────────────────


MOCK_PRODUCTS_LIST = {
    "products": {
        "nodes": [
            {
                "id": "gid://shopify/Product/1",
                "title": "Product One",
                "handle": "product-one",
                "vendor": "Vendor A",
                "status": "ACTIVE",
                "featuredMedia": {"preview": {"image": {"url": "https://cdn.example.com/1.jpg"}}},
            },
            {
                "id": "gid://shopify/Product/2",
                "title": "Product Two",
                "handle": "product-two",
                "vendor": "Vendor B",
                "status": "DRAFT",
                "featuredMedia": {"preview": {"image": {"url": "https://cdn.example.com/2.jpg"}}},
            },
        ],
        "pageInfo": {"hasNextPage": False, "endCursor": "cursor1"},
    }
}


@pytest.mark.django_db
class TestProductPicker:
    @patch("apps.generator.picker._get_client")
    def test_lists_products(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_PRODUCTS_LIST

        result = list_products(shop, "token")

        assert len(result["products"]) == 2
        assert result["products"][0]["title"] == "Product One"
        assert result["page"] == 1
        assert result["has_next"] is False

    @patch("apps.generator.picker._get_client")
    def test_search_filters(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_PRODUCTS_LIST

        result = list_products(shop, "token", search="one")

        assert len(result["products"]) == 1
        assert result["products"][0]["title"] == "Product One"

    @patch("apps.generator.picker._get_client")
    def test_source_labels(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_PRODUCTS_LIST

        # Create ProductSource for product 1
        ProductSource.objects.create(
            shop=shop,
            product_gid="gid://shopify/Product/1",
            source="printify",
            detected_by="vendor",
            created_by_mosaiq=False,
            locked_fields=["title"],
        )

        result = list_products(shop, "token")

        assert result["products"][0]["source"] == "printify"
        assert result["products"][0]["source_label"] == "Printify"
        assert result["products"][1]["source"] == "unknown_app"

    @patch("apps.generator.picker._get_client")
    def test_pagination(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = MOCK_PRODUCTS_LIST

        result = list_products(shop, "token", page=1)

        assert result["total_pages"] == 1  # 2 products / 50 per page = 1 page
