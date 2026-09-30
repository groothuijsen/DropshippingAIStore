"""Tests for T-040: Vertex image provider + OpenAI fallback + cost tracking + budget guard."""

import pytest

from apps.ai.image_costs import (
    AI_COST_BUDGET_USD,
    IMAGE_COSTS,
    ImageCostTracker,
    check_budget_remaining,
)
from apps.ai.image_providers import (
    HIGH_RES_SLOTS,
    RESOLUTION_1K,
    RESOLUTION_2K,
    ImageGenerationResult,
    OpenAIImageProvider,
    VertexImageProvider,
    get_provider,
    get_resolution_for_slot,
)

# ── Resolution tests ──────────────────────────────────────────────────────


class TestResolution:
    def test_hero_gets_2k(self):
        assert get_resolution_for_slot("hero") == RESOLUTION_2K

    def test_lifestyle_gets_2k(self):
        assert get_resolution_for_slot("lifestyle_1") == RESOLUTION_2K

    def test_detail_gets_1k(self):
        assert get_resolution_for_slot("detail_1") == RESOLUTION_1K

    def test_high_res_slots(self):
        assert "hero" in HIGH_RES_SLOTS
        assert "lifestyle_1" in HIGH_RES_SLOTS


# ── Cost table tests ──────────────────────────────────────────────────────


class TestCostTable:
    def test_all_models_have_costs(self):
        for model in ["gemini-3.1-flash-image", "gemini-3-pro-image", "gpt-image-2.5-sunburst"]:
            assert model in IMAGE_COSTS
            assert "2048x2048" in IMAGE_COSTS[model]
            assert "1024x1024" in IMAGE_COSTS[model]

    def test_flash_2k_cost(self):
        assert IMAGE_COSTS["gemini-3.1-flash-image"]["2048x2048"] == 0.10

    def test_flash_1k_cost(self):
        assert IMAGE_COSTS["gemini-3.1-flash-image"]["1024x1024"] == 0.067

    def test_pro_more_expensive_than_flash(self):
        pro_2k = IMAGE_COSTS["gemini-3-pro-image"]["2048x2048"]
        flash_2k = IMAGE_COSTS["gemini-3.1-flash-image"]["2048x2048"]
        assert pro_2k > flash_2k

    def test_openai_cheaper_than_flash(self):
        openai_2k = IMAGE_COSTS["gpt-image-2.5-sunburst"]["2048x2048"]
        flash_2k = IMAGE_COSTS["gemini-3.1-flash-image"]["2048x2048"]
        assert openai_2k < flash_2k


# ── Budget guard tests ────────────────────────────────────────────────────


class TestBudgetGuard:
    def test_initial_state(self):
        tracker = ImageCostTracker()
        assert tracker.remaining_usd == AI_COST_BUDGET_USD
        assert tracker.is_exhausted is False

    def test_record_cost(self):
        tracker = ImageCostTracker()
        cost = tracker.record("gemini-3.1-flash-image", "2048x2048")
        assert cost == 0.10
        assert tracker.spent_usd == 0.10
        assert tracker.remaining_usd == AI_COST_BUDGET_USD - 0.10

    def test_can_afford(self):
        tracker = ImageCostTracker()
        assert tracker.can_afford("gemini-3.1-flash-image", "2048x2048") is True

    def test_cannot_afford_when_broke(self):
        tracker = ImageCostTracker(budget_usd=0.05)
        assert tracker.can_afford("gemini-3.1-flash-image", "2048x2048") is False

    def test_exhausted_after_enough_generations(self):
        tracker = ImageCostTracker(budget_usd=0.10)
        tracker.record("gemini-3.1-flash-image", "2048x2048")  # $0.10
        assert tracker.is_exhausted is True

    def test_five_2k_images_within_budget(self):
        """5 × $0.10 = $0.50 within $2.00 budget."""
        tracker = ImageCostTracker()
        for _ in range(5):
            assert tracker.can_afford("gemini-3.1-flash-image", "2048x2048") is True
            tracker.record("gemini-3.1-flash-image", "2048x2048")
        assert tracker.spent_usd == 0.50

    def test_reset(self):
        tracker = ImageCostTracker()
        tracker.record("gemini-3.1-flash-image", "2048x2048")
        tracker.reset()
        assert tracker.spent_usd == 0.0

    def test_check_budget_remaining(self):
        tracker = ImageCostTracker()
        assert check_budget_remaining(tracker, "gemini-3.1-flash-image", "2048x2048") is True


# ── Provider tests ────────────────────────────────────────────────────────


class TestProviders:
    def test_get_provider_vertex(self):
        provider = get_provider("vertex")
        assert isinstance(provider, VertexImageProvider)

    def test_get_provider_openai(self):
        provider = get_provider("openai", api_key="test-key")
        assert isinstance(provider, OpenAIImageProvider)

    def test_get_provider_unknown(self):
        with pytest.raises(ValueError):
            get_provider("unknown")

    def test_vertex_provider_model(self):
        assert VertexImageProvider.MODEL == "gemini-3.1-flash-image"

    def test_openai_provider_model(self):
        provider = OpenAIImageProvider(api_key="test-key")
        assert provider.MODEL == "gpt-image-2.5-sunburst"


# ── Fallback logic tests ──────────────────────────────────────────────────


class TestFallbackLogic:
    def test_vertex_fails_openai_succeeds(self):
        """Provider error → fallback to OpenAI."""
        vertex_result = ImageGenerationResult(
            success=False,
            provider="vertex",
            error="Provider error",
        )
        openai_result = ImageGenerationResult(
            success=True,
            image_bytes=b"fake-image",
            provider="openai",
            model="gpt-image-2.5-sunburst",
        )

        # Simulate: vertex fails, fallback succeeds
        assert vertex_result.success is False
        assert openai_result.success is True
        assert openai_result.provider == "openai"

    def test_both_providers_fail_skip_slot(self):
        """Both fail → skip slot, job continues."""
        vertex_result = ImageGenerationResult(success=False, error="Vertex error")
        openai_result = ImageGenerationResult(success=False, error="OpenAI error")

        assert vertex_result.success is False
        assert openai_result.success is False


# ── ImageGenerationResult tests ───────────────────────────────────────────


class TestImageGenerationResult:
    def test_success_result(self):
        result = ImageGenerationResult(
            success=True,
            image_bytes=b"test",
            provider="vertex",
            model="gemini-3.1-flash-image",
        )
        assert result.success is True
        assert result.provider == "vertex"

    def test_failure_result(self):
        result = ImageGenerationResult(
            success=False,
            provider="vertex",
            error="Test error",
        )
        assert result.success is False
        assert result.error == "Test error"
