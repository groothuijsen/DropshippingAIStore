import pytest
from django.test import Client

pytestmark = pytest.mark.django_db
M = {"HTTP_HOST": "shopify.mosaiq.marketing"}


@pytest.fixture(autouse=True)
def _hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]


class TestGermanGate:
    def test_de_404_until_enabled(self):
        assert Client().get("/de/", **M).status_code == 404
        assert Client().get("/de/preise/", **M).status_code == 404

    def test_de_renders_when_enabled(self, settings):
        settings.MARKETING_DE_ENABLED = True
        html = Client().get("/de/", **M).content.decode()
        assert "Shopify-Shops, die in Europa verkaufen" in html
        assert "/de/fruehzugang/" in html  # install fallback + CTAs
        assert Client().get("/de/funktionen/", **M).status_code == 200
        assert Client().get("/de/eu-regeln/", **M).status_code == 200
        assert Client().get("/de/von-null/", **M).status_code == 200

    def test_de_early_access_form(self, settings):
        settings.MARKETING_DE_ENABLED = True
        html = Client().get("/de/fruehzugang/", **M).content.decode()
        assert html.count("<form method=\"post\"") == 1

    def test_nl_and_en_unaffected(self):
        assert Client().get("/", **M).status_code == 200
        assert Client().get("/nl/", **M).status_code == 200
