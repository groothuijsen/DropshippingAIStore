import pytest
from django.test import Client

pytestmark = pytest.mark.django_db
M = {"HTTP_HOST": "shopify.mosaiq.marketing"}


@pytest.fixture(autouse=True)
def _hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]


class TestHelpCentre:
    def test_help_index_lists_six_articles(self):
        html = Client().get("/help/", **M).content.decode()
        for slug in ('installation', 'blocks-and-templates', 'start-from-zero', 'compliance-check', 'billing', 'uninstall'):
            assert f"/help/{slug}/" in html, slug

    def test_help_article_renders(self):
        html = Client().get("/help/installation/", **M).content.decode()
        assert "How to install Mosaiq" in html


class TestBlog:
    def test_drafts_hidden_by_default(self):
        html = Client().get("/blog/", **M).content.decode()
        assert "30-day price rule" not in html

    def test_drafts_shown_with_setting(self, settings):
        settings.MARKETING_SHOW_DRAFTS = True
        html = Client().get("/blog/", **M).content.decode()
        assert "/blog/eu-30-day-price-rule/" in html and "draft" in html

    def test_blog_post_with_drafts_on(self, settings):
        settings.MARKETING_SHOW_DRAFTS = True
        html = Client().get("/blog/eu-30-day-price-rule/", **M).content.decode()
        assert "Omnibus" in html and "not legal advice" in html

    def test_rss_feed(self, settings):
        settings.MARKETING_SHOW_DRAFTS = True
        xml = Client().get("/blog/rss.xml", **M).content.decode()
        assert "<rss" in xml and "/blog/eu-30-day-price-rule/" in xml

    def test_rss_empty_without_drafts(self):
        xml = Client().get("/blog/rss.xml", **M).content.decode()
        assert "<item>" not in xml
