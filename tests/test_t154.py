"""T-154 — SEO: sitemap, robots, canonical, hreflang, JSON-LD."""

from datetime import date

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db
M = {"HTTP_HOST": "shopify.mosaiq.marketing"}
A = {"HTTP_HOST": "shop.mosaiq.marketing"}


@pytest.fixture(autouse=True)
def _hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]


class TestSitemap:
    def test_sitemap_lists_all_pages(self):
        xml = Client().get("/sitemap.xml", **M).content.decode()
        assert "<urlset" in xml
        for loc in ("/</loc>", "/features/", "/nl/prijzen/", "/nl/eu-regels/", "/compare/"):
            assert loc in xml
        assert f"<lastmod>{date.today().isoformat()}</lastmod>" in xml
        assert 'hreflang="nl"' in xml


class TestRobots:
    def test_marketing_allows_and_points_to_sitemap(self):
        body = Client().get("/robots.txt", **M).content.decode()
        assert "Allow: /" in body and "/sitemap.xml" in body

    def test_app_host_blocks_app_paths(self):
        body = Client().get("/robots.txt", **A).content.decode()
        assert "Disallow: /app/" in body


class TestHeadTags:
    def test_canonical_hreflang_jsonld_on_home(self):
        html = Client().get("/", **M).content.decode()
        assert '<link rel="canonical" href="https://shopify.mosaiq.marketing/">' in html
        assert 'hreflang="x-default"' in html and 'hreflang="nl"' in html
        assert '"@type":"SoftwareApplication"' in html
        assert '"price":"29"' in html  # rendered from plans.py, not typed in copy

    def test_nl_page_canonical(self):
        html = Client().get("/nl/prijzen/", **M).content.decode()
        assert 'href="https://shopify.mosaiq.marketing/nl/prijzen/"' in html


class TestBeacon:
    def test_beacon_logs_hit_no_cookies(self):
        from apps.marketing.models import MarketingHit

        resp = Client().get("/t.gif", {"p": "/", "r": "https://example.com/x", "l": "en"}, **M)
        assert resp.status_code == 200
        assert resp["Content-Type"] == "image/gif"
        assert "Set-Cookie" not in resp
        hit = MarketingHit.objects.get(path="/")
        assert hit.referrer_host == "example.com" and hit.lang == "en"

    def test_beacon_rejects_bad_host(self):
        assert Client().get("/t.gif", {"p": "/"}, **A).status_code == 404
