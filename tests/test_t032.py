"""Tests for T-032: Theme App Extension scaffold, locales check, deep links."""

import json
from pathlib import Path

from apps.core.deep_links import (
    BLOCK_TARGETS,
    EMBED_TARGETS,
    get_add_block_link,
    get_configure_embed_link,
)

EXTENSIONS_DIR = Path(__file__).parent.parent / "extensions" / "theme-blocks"
LOCALES_DIR = EXTENSIONS_DIR / "locales"


# ── Extension scaffold tests ──────────────────────────────────────────────


class TestExtensionScaffold:
    def test_toml_exists(self):
        assert (EXTENSIONS_DIR / "shopify.ui.extension.toml").exists()

    def test_blocks_exist(self):
        blocks_dir = EXTENSIONS_DIR / "blocks"
        assert blocks_dir.exists()
        block_files = list(blocks_dir.glob("*.liquid"))
        assert len(block_files) >= 4  # mq-page-sections, mq-gpsr, mq-price, mq-bundle-picker

    def test_embeds_exist(self):
        # mq-tokens, mq-cart-drawer, mq-withdrawal-link
        tokens = EXTENSIONS_DIR / "blocks" / "mq-tokens.liquid"
        assert tokens.exists()

    def test_mq_tokens_uses_app_namespace(self):
        content = (EXTENSIONS_DIR / "blocks" / "mq-tokens.liquid").read_text()
        assert "$app:mosaiq" in content
        assert "design_tokens" in content

    def test_mq_tokens_no_google_fonts(self):
        """No external font services (F06 criterion 9)."""
        content = (EXTENSIONS_DIR / "blocks" / "mq-tokens.liquid").read_text()
        assert "fonts.googleapis.com" not in content
        assert "fonts.gstatic.com" not in content

    def test_blocks_render_nothing_if_missing(self):
        """Every block renders nothing if metafield is missing (F06 criterion 2)."""
        for block_file in (EXTENSIONS_DIR / "blocks").glob("*.liquid"):
            content = block_file.read_text()
            has_guard = "{%- if" in content or "{% if" in content
            assert has_guard, f"{block_file.name} missing if-guard"


# ── Locales tests ─────────────────────────────────────────────────────────


class TestLocales:
    def test_locale_files_exist(self):
        assert (LOCALES_DIR / "en.default.json").exists()
        assert (LOCALES_DIR / "nl.json").exists()
        assert (LOCALES_DIR / "de.json").exists()

    def test_all_locales_have_same_keys(self):
        """All locale files must have the same keys (F06 criterion 4)."""

        def get_nested_keys(obj, prefix=""):
            keys = set()
            for key, value in obj.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    keys.update(get_nested_keys(value, full_key))
                else:
                    keys.add(full_key)
            return keys

        with open(LOCALES_DIR / "en.default.json") as f:
            en = json.load(f)
        with open(LOCALES_DIR / "nl.json") as f:
            nl = json.load(f)
        with open(LOCALES_DIR / "de.json") as f:
            de = json.load(f)

        en_keys = get_nested_keys(en)
        nl_keys = get_nested_keys(nl)
        de_keys = get_nested_keys(de)

        assert en_keys == nl_keys, f"EN vs NL: {en_keys ^ nl_keys}"
        assert en_keys == de_keys, f"EN vs DE: {en_keys ^ de_keys}"

    def test_nl_translations_are_dutch(self):
        with open(LOCALES_DIR / "nl.json") as f:
            nl = json.load(f)
        assert nl["gpsr"]["heading"] == "Productinformatie"
        assert nl["withdrawal"]["link"] == "Overeenkomst ontbinden"

    def test_de_translations_are_german(self):
        with open(LOCALES_DIR / "de.json") as f:
            de = json.load(f)
        assert de["gpsr"]["heading"] == "Produktinformationen"
        assert de["withdrawal"]["link"] == "Vertrag widerrufen"


# ── Deep links tests ──────────────────────────────────────────────────────


class TestDeepLinks:
    def test_add_block_link(self):
        link = get_add_block_link(
            "mystore.myshopify.com",
            "abc123",
            "mq-price",
            "product",
        )
        assert link == (
            "https://mystore.myshopify.com/admin/themes/current/editor"
            "?template=product"
            "&addAppBlockId=abc123/mq-price"
            "&target=mainSection"
        )

    def test_add_block_link_custom_target(self):
        link = get_add_block_link(
            "mystore.myshopify.com",
            "abc123",
            "mq-page-sections",
            "page",
            target="mainSection",
        )
        assert "target=mainSection" in link

    def test_configure_embed_link(self):
        link = get_configure_embed_link(
            "mystore.myshopify.com",
            "abc123",
            "mq-tokens",
        )
        assert "addAppBlockId=abc123/mq-tokens" in link

    def test_block_targets_defined(self):
        assert BLOCK_TARGETS["mq-price"] == "mainSection"
        assert BLOCK_TARGETS["mq-page-sections"] == "mainSection"
        assert BLOCK_TARGETS["mq-gpsr"] == "mainSection"

    def test_embed_targets_defined(self):
        assert EMBED_TARGETS["mq-tokens"] == "head"
        assert EMBED_TARGETS["mq-cart-drawer"] == "body"
        assert EMBED_TARGETS["mq-withdrawal-link"] == "body"


# ── Locales check script test ─────────────────────────────────────────────


class TestCheckLoccalesScript:
    def test_script_exists(self):
        script = Path(__file__).parent.parent / "scripts" / "check_locales.py"
        assert script.exists()

    def test_script_runs_clean(self):
        """The check script should pass on current locale files."""
        import subprocess
        import sys

        script = Path(__file__).parent.parent / "scripts" / "check_locales.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=script.parent.parent,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert "All locale files are in sync" in result.stdout
