"""T-151 — site design: fonts, tokens, templates, OG image, no third-party requests."""

from importlib.util import find_spec
from pathlib import Path

import pytest
from django.contrib.staticfiles import finders
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _allow_hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]

MARKETING = {"HTTP_HOST": "shopify.mosaiq.marketing"}


def _get(path: str) -> str:
    return Client().get(path, **MARKETING).content.decode()


class TestNoThirdPartyRequests:
    def test_home_has_no_external_assets(self):
        html = _get("/")
        assert "fonts.googleapis" not in html
        assert "cdn." not in html
        for needle in ("<link", "<script", "@import"):
            assert f"{needle}[^>]*http" not in html.replace("\n", " ")
        import re

        assert not re.search(r'<link[^>]+href="https?://', html)
        assert not re.search(r'<script[^>]+src="https?://', html)
        assert "url(http" not in html

    def test_features_page_renders_styled(self):
        html = _get("/features/")
        assert "tokens.css" in html and "site.css" in html


class TestFontsAndTokens:
    def test_outfit_variable_font_self_hosted(self):
        matches = finders.find("marketing/fonts/outfit-variable.woff2")
        assert matches and Path(matches).stat().st_size > 10_000

    def test_ofl_licence_ships_with_fonts(self):
        matches = finders.find("marketing/fonts/OFL.txt")
        assert matches and "MIT License" not in Path(matches).read_text()  # OFL, not MIT
        assert "SIL OPEN FONT LICENSE" in Path(matches).read_text().upper()

    def test_tokens_direction_c(self):
        css = Path(finders.find("marketing/css/tokens.css")).read_text()
        assert "--acc: #E8542F" in css
        assert "--bg: #FAFAF8" in css
        assert "Outfit" in css


@pytest.mark.skipif(find_spec("PIL") is None, reason="Pillow not installed")
class TestOgImage:
    def test_og_image_1200x630(self, tmp_path):
        from django.core.management import call_command

        call_command("generate_og_image")
        from PIL import Image

        path = Path(finders.find("marketing/og/home-1200x630.png"))
        assert Image.open(path).size == (1200, 630)
