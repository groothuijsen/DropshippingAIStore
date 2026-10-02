import pytest
from django.test import Client

pytestmark = pytest.mark.django_db
M = {"HTTP_HOST": "shopify.mosaiq.marketing"}


@pytest.fixture(autouse=True)
def _hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]
    settings.MARKETING_LEGAL_NAME = "Mosaiq B.V."
    settings.MARKETING_ADDRESS = "Teststraat 1, Amsterdam"
    settings.MARKETING_REG_NO = "12345678"
    settings.MARKETING_VAT_ID = "NL123456789B01"


class TestLegalPages:
    def test_all_legal_pages_render_with_draft_banner(self):
        for path in ('/legal/privacy/', '/legal/terms/', '/legal/dpa/', '/legal/subprocessors/', '/legal/cookies/', '/legal/company/'):
            html = Client().get(path, **M).content.decode()
            assert "draft-banner" in html, path
            assert "Mosaiq B.V." in html, path  # placeholder resolved

    def test_nl_legal_pages(self):
        html = Client().get("/nl/juridisch/privacy/", **M).content.decode()
        assert "draft-banner" in html and "Privacyverklaring" in html

    def test_footer_has_legal_links_and_company(self):
        html = Client().get("/", **M).content.decode()
        assert "/legal/privacy/" in html and "footer-company" in html
        assert "KvK 12345678" in html

    def test_placeholder_fallback_without_settings(self, settings):
        settings.MARKETING_LEGAL_NAME = ""
        html = Client().get("/legal/company/", **M).content.decode()
        assert "[company legal name]" in html
