"""T-150: marketing app foundation (F19-1, 2; 13 §2–4).

Host guard (only shopify.mosaiq.marketing), language-prefixed routes,
Markdown content loader with section schemas, check_marketing_content.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from apps.marketing.content import list_pages, load_page
from apps.marketing.schemas import SECTIONS, validate_sections

MARKETING_HOST = "shopify.mosaiq.marketing"
APP_HOST = "shop.mosaiq.marketing"


@pytest.fixture(autouse=True)
def _any_host(settings):
    settings.ALLOWED_HOSTS = ["*"]


def _get(path: str, host: str) -> object:
    return Client().get(path, HTTP_HOST=host)


class TestHostGuard:
    def test_marketing_host_serves_home(self):
        resp = _get("/", MARKETING_HOST)
        assert resp.status_code == 200

    def test_marketing_host_serves_features(self):
        resp = _get("/features/", MARKETING_HOST)
        assert resp.status_code == 200

    def test_marketing_host_language_route(self):
        resp = _get("/nl/", MARKETING_HOST)
        assert resp.status_code == 200

    def test_app_host_subpaths_404(self):
        for path in ("/features/", "/pricing/", "/eu-compliance/", "/nl/"):
            resp = _get(path, APP_HOST)
            assert resp.status_code == 404, path

    def test_app_host_root_redirects_to_app(self):
        """03 §2.1: the embedded app entry point survives."""
        resp = _get("/", APP_HOST)
        assert resp.status_code == 302
        assert resp["Location"].endswith("/app/")

    def test_other_host_404(self):
        assert _get("/features/", "example.com").status_code == 404


class TestContentLoader:
    def test_load_page_parses_front_matter_and_sections(self):
        page = load_page("en", "home")
        assert page["title"]
        assert page["slug"] == "/"
        assert isinstance(page["sections"], list)
        assert page["sections"], "home.md must define at least one section"

    def test_list_pages_finds_all_languages(self):
        pages = list_pages("en")
        assert "home" in pages
        assert "features" in pages
        assert "pricing" in pages


class TestSectionSchemas:
    def test_known_section_types_registered(self):
        for name in ("hero", "steps", "features", "faq", "cta", "pricing_table", "comparison"):
            assert name in SECTIONS

    def test_valid_sections_pass(self):
        sections = [
            {"type": "hero", "eyebrow": "EU compliance", "headline": "Build a store that follows the rules",
             "sub": "Dutch and German rules built in.", "cta_primary": {"label": "Get early access", "href": "@early_access"}},
            {"type": "faq", "items": [{"q": "What is Mosaiq?", "a": "An embedded Shopify app."}]},
        ]
        errors = validate_sections(sections)
        assert errors == []

    def test_invalid_section_fails(self):
        errors = validate_sections([{"type": "hero", "headline": "x"}])  # missing sub/cta
        assert errors
        errors = validate_sections([{"type": "unknown_section", "foo": "bar"}])
        assert errors

    def test_hero_headline_length_limit(self):
        sections = [{"type": "hero", "eyebrow": "e", "headline": "x" * 71, "sub": "s",
                     "cta_primary": {"label": "Go", "href": "@early_access"}}]
        assert validate_sections(sections)


class TestCheckCommand:
    def test_command_passes_with_current_content(self):
        call_command("check_marketing_content")  # must not raise

    def test_command_fails_on_broken_content(self, tmp_path, settings):
        import pathlib

        content_root = pathlib.Path(settings.BASE_DIR) / "content" / "marketing" / "en"
        backup = (content_root / "home.md").read_text()
        try:
            (content_root / "home.md").write_text(
                "---\ntitle: Broken\nslug: /\ntemplate: marketing/page_default.html\nsections:\n  - type: hero\n"
                "---\nBody.\n"
            )
            with pytest.raises(CommandError):
                call_command("check_marketing_content")
        finally:
            (content_root / "home.md").write_text(backup)

    def test_salespage_removed(self, settings):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("apps.core.salespage")
