"""Tests for T-030: BrandKit, presets, fonts, palette validation, design tokens."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.themes.fonts import (
    BUNDLED_FONTS,
    THEME_FONT_KEY,
    get_font_css,
    get_font_keys,
    is_valid_font,
)
from apps.themes.models import BrandKit
from apps.themes.presets import STYLE_PRESETS, get_preset, get_preset_names
from apps.themes.tokens import build_design_tokens, sync_tokens_to_metafield
from apps.themes.validation import (
    contrast_ratio,
    hex_to_rgb,
    is_valid_hex,
    relative_luminance,
    validate_palette,
)


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


VALID_PALETTE = {
    "primary": "#1A1A2E",
    "secondary": "#16213E",
    "accent": "#E94560",
    "background": "#FFFFFF",
    "text": "#1A1A1A",
}


@pytest.fixture
def brandkit(shop):
    return BrandKit.objects.create(
        shop=shop,
        brand_name="Test Brand",
        tone="warm",
        palette=VALID_PALETTE,
        style_preset="clean",
    )


# ── Font tests ────────────────────────────────────────────────────────────


class TestFonts:
    def test_six_bundled_fonts(self):
        assert len(BUNDLED_FONTS) == 6

    def test_font_keys_include_theme(self):
        keys = get_font_keys()
        assert THEME_FONT_KEY in keys
        assert len(keys) == 7  # 6 fonts + theme

    def test_valid_fonts(self):
        assert is_valid_font("inter") is True
        assert is_valid_font("manrope") is True
        assert is_valid_font("theme") is True
        assert is_valid_font("nonexistent") is False

    def test_font_css(self):
        assert get_font_css("inter") == "'Inter', sans-serif"
        assert get_font_css("lora") == "'Lora', serif"
        assert get_font_css("theme") == "inherit"
        assert get_font_css("") == "inherit"


# ── Preset tests ──────────────────────────────────────────────────────────


class TestPresets:
    def test_six_presets(self):
        assert len(STYLE_PRESETS) == 6

    def test_preset_names(self):
        names = get_preset_names()
        assert "clean" in names
        assert "bold" in names
        assert "organic" in names
        assert "luxe" in names
        assert "tech" in names
        assert "soft" in names

    def test_get_preset(self):
        p = get_preset("clean")
        assert p["radius"]["base"] == "8px"
        assert p["button"]["style"] == "solid"

    def test_unknown_preset_defaults_to_clean(self):
        p = get_preset("nonexistent")
        assert p == STYLE_PRESETS["clean"]

    def test_presets_visibly_different(self):
        """Two stores with different presets should have different values."""
        clean = get_preset("clean")
        luxe = get_preset("luxe")
        assert clean["radius"]["base"] != luxe["radius"]["base"]
        assert clean["heading"]["font_weight"] != luxe["heading"]["font_weight"]


# ── Palette validation tests ──────────────────────────────────────────────


class TestHexValidation:
    def test_valid_hex(self):
        assert is_valid_hex("#FFFFFF") is True
        assert is_valid_hex("#1a2b3c") is True
        assert is_valid_hex("#000000") is True

    def test_invalid_hex(self):
        assert is_valid_hex("#FFF") is False  # 3-digit
        assert is_valid_hex("#GGGGGG") is False
        assert is_valid_hex("FFFFFF") is False  # no hash
        assert is_valid_hex("#FFFFF") is False  # 5-digit

    def test_hex_to_rgb(self):
        assert hex_to_rgb("#FFFFFF") == (255, 255, 255)
        assert hex_to_rgb("#000000") == (0, 0, 0)
        assert hex_to_rgb("#FF0000") == (255, 0, 0)


class TestContrast:
    def test_black_on_white(self):
        ratio = contrast_ratio("#000000", "#FFFFFF")
        assert ratio > 20  # Very high contrast

    def test_white_on_white(self):
        ratio = contrast_ratio("#FFFFFF", "#FFFFFF")
        assert ratio == 1.0

    def test_valid_palette_contrast(self):
        ratio = contrast_ratio(VALID_PALETTE["text"], VALID_PALETTE["background"])
        assert ratio >= 4.5

    def test_relative_luminance(self):
        assert relative_luminance("#FFFFFF") == pytest.approx(1.0, abs=0.01)
        assert relative_luminance("#000000") == pytest.approx(0.0, abs=0.01)


class TestPaletteValidation:
    def test_valid_palette(self):
        result = validate_palette(VALID_PALETTE)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_missing_key(self):
        bad = {k: v for k, v in VALID_PALETTE.items() if k != "accent"}
        result = validate_palette(bad)
        assert result["valid"] is False
        assert "Missing palette key: accent" in result["errors"]

    def test_invalid_hex(self):
        bad = {**VALID_PALETTE, "primary": "#XYZ"}
        result = validate_palette(bad)
        assert result["valid"] is False
        assert any("Invalid hex" in e for e in result["errors"])

    def test_low_contrast(self):
        bad = {**VALID_PALETTE, "text": "#CCCCCC", "background": "#FFFFFF"}
        result = validate_palette(bad)
        assert result["valid"] is False
        assert any("Contrast too low" in e for e in result["errors"])
        assert "text" in result["suggestions"]

    def test_suggestion_is_darker(self):
        bad = {**VALID_PALETTE, "text": "#CCCCCC", "background": "#FFFFFF"}
        result = validate_palette(bad)
        suggestion = result["suggestions"]["text"]
        assert is_valid_hex(suggestion)
        assert contrast_ratio(suggestion, "#FFFFFF") >= 4.5


# ── Design tokens tests ───────────────────────────────────────────────────


class TestDesignTokens:
    def test_build_tokens(self, brandkit):
        tokens = build_design_tokens(brandkit)
        assert tokens["brand_name"] == "Test Brand"
        assert tokens["palette"]["primary"] == "#1A1A2E"
        assert tokens["fonts"]["heading"] == "inherit"  # empty font = inherit
        assert tokens["style_preset"] == "clean"
        assert "radius" in tokens
        assert "button" in tokens

    def test_tokens_with_fonts(self, shop):
        bk = BrandKit.objects.create(
            shop=shop,
            brand_name="FB",
            tone="premium",
            palette=VALID_PALETTE,
            style_preset="luxe",
            font_heading="lora",
            font_body="inter",
        )
        tokens = build_design_tokens(bk)
        assert tokens["fonts"]["heading"] == "'Lora', serif"
        assert tokens["fonts"]["body"] == "'Inter', sans-serif"

    def test_tokens_preset_values(self, shop):
        bk = BrandKit.objects.create(
            shop=shop,
            brand_name="PB",
            tone="sporty",
            palette=VALID_PALETTE,
            style_preset="tech",
        )
        tokens = build_design_tokens(bk)
        assert tokens["radius"]["base"] == "6px"
        assert tokens["button"]["text_transform"] == "uppercase"


@pytest.mark.django_db
class TestSyncTokens:
    @patch("apps.themes.tokens.settings_api_version", return_value="2026-07")
    @patch("apps.core.shopify_client.ShopifyGraphQLClient.execute")
    def test_sync_sets_tokens_synced_at(self, mock_execute, mock_version, shop, brandkit):
        mock_execute.return_value = {"metafieldsSet": {"metafields": [], "userErrors": []}}

        result = sync_tokens_to_metafield(shop, "token", brandkit)

        assert result is True
        brandkit.refresh_from_db()
        assert brandkit.tokens_synced_at is not None

    @patch("apps.themes.tokens.settings_api_version", return_value="2026-07")
    @patch("apps.core.shopify_client.ShopifyGraphQLClient.execute")
    def test_sync_user_errors_returns_false(self, mock_execute, mock_version, shop, brandkit):
        mock_execute.return_value = {"metafieldsSet": {"metafields": [], "userErrors": [{"message": "bad"}]}}

        result = sync_tokens_to_metafield(shop, "token", brandkit)

        assert result is False
        brandkit.refresh_from_db()
        assert brandkit.tokens_synced_at is None
