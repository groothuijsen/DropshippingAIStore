"""Tests for T-031: onboarding flow — state machine, step navigation."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.core.onboarding import (
    ONBOARDING_STEPS,
    advance,
    get_current_step,
    get_next_step,
    get_prev_step,
    get_step_data,
    go_back,
    is_complete,
    set_step,
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
        onboarding_step="language",
    )


# ── Step navigation tests ─────────────────────────────────────────────────


class TestStepNavigation:
    def test_step_order(self):
        assert ONBOARDING_STEPS == ["language", "brand", "sources", "theme", "withdrawal", "done"]

    def test_get_current_step(self, shop):
        assert get_current_step(shop) == "language"

    def test_get_next_step(self):
        assert get_next_step("language") == "brand"
        assert get_next_step("brand") == "sources"
        assert get_next_step("sources") == "theme"
        assert get_next_step("theme") == "withdrawal"
        assert get_next_step("withdrawal") == "done"
        assert get_next_step("done") is None

    def test_get_prev_step(self):
        assert get_prev_step("brand") == "language"
        assert get_prev_step("sources") == "brand"
        assert get_prev_step("language") is None
        assert get_prev_step("done") == "withdrawal"

    def test_set_step(self, shop):
        set_step(shop, "brand")
        shop.refresh_from_db()
        assert shop.onboarding_step == "brand"

    def test_set_invalid_step_raises(self, shop):
        with pytest.raises(ValueError, match="Invalid onboarding step"):
            set_step(shop, "invalid")

    def test_advance(self, shop):
        result = advance(shop)
        assert result == "brand"
        shop.refresh_from_db()
        assert shop.onboarding_step == "brand"

    def test_advance_from_done_returns_none(self, shop):
        shop.onboarding_step = "done"
        shop.save(update_fields=["onboarding_step"])
        result = advance(shop)
        assert result is None

    def test_go_back(self, shop):
        shop.onboarding_step = "brand"
        shop.save(update_fields=["onboarding_step"])
        result = go_back(shop)
        assert result == "language"
        shop.refresh_from_db()
        assert shop.onboarding_step == "language"

    def test_go_back_from_first_step(self, shop):
        result = go_back(shop)
        assert result is None

    def test_is_complete(self, shop):
        assert is_complete(shop) is False
        shop.onboarding_step = "done"
        shop.save(update_fields=["onboarding_step"])
        assert is_complete(shop) is True

    def test_full_flow(self, shop):
        """Walk through all steps."""
        for expected in ["brand", "sources", "theme", "withdrawal", "done"]:
            result = advance(shop)
            assert result == expected
        shop.refresh_from_db()
        assert shop.onboarding_step == "done"

    def test_resume_after_interruption(self, shop):
        """Stopping halfway and returning later resumes at the last step."""
        advance(shop)  # → brand
        advance(shop)  # → sources
        # Simulate new session — get_current_step returns saved step
        assert get_current_step(shop) == "sources"


# ── Step data tests ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestStepData:
    def test_language_step_data(self, shop):
        data = get_step_data(shop, "language")
        assert data["current_locale"] == "en"
        assert "nl" in data["available_locales"]

    def test_brand_step_data(self, shop):
        data = get_step_data(shop, "brand")
        assert "presets" in data
        assert "tones" in data
        assert data["brandkit"] is None

    def test_sources_step_data(self, shop):
        data = get_step_data(shop, "sources")
        assert "import_apps" in data
        assert "available_apps" in data
        assert "dsers" in data["available_apps"]

    def test_theme_step_data(self, shop):
        data = get_step_data(shop, "theme")
        assert "blocks" in data
        assert "embeds" in data
        assert "mq-page-sections" in data["blocks"]

    def test_withdrawal_step_data(self, shop):
        data = get_step_data(shop, "withdrawal")
        assert data["step"] == "withdrawal"


# ── BrandKit integration tests ────────────────────────────────────────────


@pytest.mark.django_db
class TestBrandStepIntegration:
    def test_brandkit_created_on_step(self, shop):
        from apps.themes.models import BrandKit

        BrandKit.objects.create(
            shop=shop,
            brand_name="Test",
            tone="warm",
            palette={
                "primary": "#000000",
                "secondary": "#666666",
                "accent": "#FF0000",
                "background": "#FFFFFF",
                "text": "#1A1A1A",
            },
            style_preset="clean",
        )

        data = get_step_data(shop, "brand")
        assert data["brandkit"] is not None
        assert data["brandkit"].brand_name == "Test"
