"""Tests for T-011: AI schemas, Anthropic client, prompt rendering, cost logging."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from apps.ai.anthropic_client import (
    AnthropicClient,
    AnthropicToolCallError,
    calculate_cost,
    call_ai,
    log_ai_call,
)
from apps.ai.prompts import load_prompt, render_prompt
from apps.ai.schemas import (
    Angle,
    FaqItem,
    FidelityResult,
    Finding,
    Hero,
    ImportResult,
    JobInput,
    ManualProduct,
    PaletteSuggestion,
    Persona,
    ResearchResult,
    SectionsPayload,
    UrlFacts,
)
from apps.core.crypto import encrypt_token
from apps.core.models import Shop
from apps.generator.models import AiCall, GenerationJob, JobStep

# ── Schemas tests ─────────────────────────────────────────────────────────


class TestSchemas:
    def test_job_input_exactly_one_source(self):
        with pytest.raises(ValidationError):
            JobInput(kind="page", content_locale="nl", style_preset="clean")
        with pytest.raises(ValidationError):
            JobInput(
                kind="page",
                content_locale="nl",
                style_preset="clean",
                product_gid="gid://shopify/Product/1",
                manual=ManualProduct(title="Test", description="x" * 30),
            )

    def test_job_input_valid_product(self):
        j = JobInput(
            kind="page",
            content_locale="nl",
            style_preset="clean",
            product_gid="gid://shopify/Product/1",
        )
        assert j.product_gid == "gid://shopify/Product/1"

    def test_manual_product(self):
        m = ManualProduct(title="Test Product", description="x" * 30)
        assert m.title == "Test Product"
        assert m.specs == {}

    def test_manual_product_min_lengths(self):
        with pytest.raises(ValidationError):
            ManualProduct(title="ab", description="x" * 30)
        with pytest.raises(ValidationError):
            ManualProduct(title="Test", description="short")

    def test_import_result(self):
        ir = ImportResult(
            product_gid="gid://shopify/Product/1",
            source_app="manual",
            title="Test Product",
            facts=["fact1", "fact2"],
            specs={"color": "black"},
            reference_image_urls=["https://example.com/img.jpg"],
            price=Decimal("29.99"),
            currency="EUR",
            locked_fields=["price"],
        )
        assert ir.source_app == "manual"

    def test_research_result_valid(self):
        rr = ResearchResult(
            niche="wellness_sleep",
            product_summary="A sleep mask",
            personas=[
                Persona(id="p1", name="Busy Parent", description="D", pains=["a", "b"], desires=["c", "d"]),
                Persona(id="p2", name="Traveler", description="D", pains=["a", "b"], desires=["c", "d"]),
            ],
            angles=[
                Angle(id="a1", title="Sleep Better", hook="h", persona_id="p1"),
                Angle(id="a2", title="Travel Ready", hook="h", persona_id="p2"),
                Angle(id="a3", title="Gift Idea", hook="h", persona_id="p1"),
            ],
            usps=["us1", "us2", "us3"],
            objections=["obj1", "obj2"],
            faq=[FaqItem(q="q", a="a") for _ in range(4)],
            claim_risks=["no medical claims"],
        )
        assert rr.niche == "wellness_sleep"

    def test_research_result_min_constraints(self):
        with pytest.raises(ValidationError):
            ResearchResult(
                niche="other",
                product_summary="s",
                personas=[],
                angles=[],
                usps=[],
                objections=[],
                faq=[],
                claim_risks=[],
            )

    def test_persona_id_pattern(self):
        with pytest.raises(ValidationError):
            Persona(id="p4", name="X", description="D", pains=["a", "b"], desires=["c", "d"])
        with pytest.raises(ValidationError):
            Persona(id="x1", name="X", description="D", pains=["a", "b"], desires=["c", "d"])

    def test_hero_section(self):
        h = Hero(headline="Great Product", subheadline="Best ever", cta_label="Buy Now")
        assert h.type == "hero"
        assert h.image_slot == "hero"

    def test_sections_payload(self):
        sp = SectionsPayload(
            locale="nl",
            page_type="pdp",
            seo_title="Test Product | Best",
            seo_description="A" * 100,
            sections=[
                Hero(headline="H", subheadline="S", cta_label="CTA"),
                Hero(headline="H2", subheadline="S2", cta_label="CTA2"),
            ],
        )
        assert sp.locale == "nl"

    def test_sections_payload_constraints(self):
        with pytest.raises(ValidationError):
            SectionsPayload(
                locale="nl",
                page_type="pdp",
                seo_title="T",
                seo_description="D",
                sections=[],
            )

    def test_url_facts(self):
        uf = UrlFacts(title="Product", facts=["f1"], specs={"color": "red"})
        assert uf.title == "Product"

    def test_palette_pattern(self):
        p = PaletteSuggestion(
            primary="#1a2b3c",
            secondary="#ffffff",
            accent="#ff0000",
            background="#f0f0f0",
            text="#333333",
            rationale="Matching the brand",
        )
        assert p.primary == "#1a2b3c"

    def test_palette_invalid_hex(self):
        with pytest.raises(ValidationError):
            PaletteSuggestion(
                primary="not-hex",
                secondary="#ffffff",
                accent="#ff0000",
                background="#f0f0f0",
                text="#333333",
                rationale="r",
            )

    def test_fidelity_result(self):
        fr = FidelityResult(same_product=True, issues=[])
        assert fr.same_product is True

    def test_finding(self):
        f = Finding(
            rule_id="EMPCO_GENERIC",
            severity="block",
            section_index=0,
            field_path="headline",
            excerpt="Duurzaam product",
            suggestion="Remove the claim",
        )
        assert f.severity == "block"


# ── Cost calculation tests ────────────────────────────────────────────────


class TestCalculateCost:
    def test_sonnet_pricing(self):
        cost = calculate_cost("claude-sonnet-5-5", 1000000, 1000000)
        assert cost == Decimal("18.0000")  # $3 input + $15 output

    def test_haiku_pricing(self):
        cost = calculate_cost("claude-haiku-4-5-20251001", 1000000, 1000000)
        assert cost == Decimal("6.0000")  # $1 input + $5 output

    def test_small_call(self):
        cost = calculate_cost("claude-sonnet-5-5", 500, 200)
        expected = Decimal("500") / Decimal("1000000") * Decimal("3") + Decimal("200") / Decimal("1000000") * Decimal(
            "15"
        )
        assert cost == expected.quantize(Decimal("0.0001"))

    def test_unknown_model_uses_default(self):
        cost = calculate_cost("unknown-model", 1000000, 1000000)
        assert cost == Decimal("18.0000")  # Default pricing

    def test_zero_tokens(self):
        cost = calculate_cost("claude-sonnet-5-5", 0, 0)
        assert cost == Decimal("0.0000")


# ── Anthropic client tests ────────────────────────────────────────────────


class TestAnthropicClient:
    def test_tool_input_extraction(self):
        response = {
            "content": [
                {"type": "text", "text": "Here's the result"},
                {"type": "tool_use", "name": "submit_test", "input": {"key": "value"}},
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        result = AnthropicClient._extract_tool_input(response, "submit_test")
        assert result == {"key": "value"}

    def test_tool_input_missing_raises(self):
        response = {"content": [{"type": "text", "text": "No tool"}]}
        with pytest.raises(AnthropicToolCallError):
            AnthropicClient._extract_tool_input(response, "submit_test")

    def test_missing_tool_use_triggers_nudge_retry(self):
        """Without forced tool_choice the model may answer in plain text;
        call() retries once with an explicit tool-call nudge (T-117 live)."""
        from pydantic import BaseModel

        class Simple(BaseModel):
            key: str

        text_only = {"content": [{"type": "text", "text": "plain answer"}], "usage": {}}
        with_tool = {
            "content": [{"type": "tool_use", "name": "submit_test", "input": {"key": "v"}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        client = AnthropicClient(api_key="test-key")
        client._make_request = MagicMock(side_effect=[text_only, with_tool])
        validated, usage = client.call(
            model="m",
            system="sys",
            user="usr",
            schema=Simple,
            tool_name="submit_test",
        )
        assert validated.key == "v"
        assert client._make_request.call_count == 2
        second_messages = client._make_request.call_args_list[1].kwargs["messages"]
        assert any("MUST submit the result" in str(m.get("content", "")) for m in second_messages if m["role"] == "user")

    def test_usage_extraction(self):
        response = {"usage": {"input_tokens": 200, "output_tokens": 100}}
        usage = AnthropicClient._extract_usage(response)
        assert usage["input_tokens"] == 200
        assert usage["output_tokens"] == 100

    def test_usage_missing_defaults(self):
        usage = AnthropicClient._extract_usage({})
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0

    @patch("apps.ai.anthropic_client.httpx.Client")
    def test_successful_call(self, mock_httpx_class):
        mock_client = MagicMock()
        mock_httpx_class.return_value = mock_client
        mock_client.post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "content": [
                    {"type": "tool_use", "name": "submit_fidelity", "input": {"same_product": True, "issues": []}}
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        )

        client = AnthropicClient(api_key="test-key")
        result, usage = client.call(
            model="claude-haiku-4-5-20251001",
            system="Test system",
            user="Test user",
            schema=FidelityResult,
            tool_name="submit_fidelity",
        )
        assert result.same_product is True
        assert usage["input_tokens"] == 100

    @patch("apps.ai.anthropic_client.httpx.Client")
    def test_retry_on_provider_error(self, mock_httpx_class):
        mock_client = MagicMock()
        mock_httpx_class.return_value = mock_client

        # First call: 529 (retryable), second: 200
        mock_client.post.side_effect = [
            MagicMock(status_code=529, text="overloaded"),
            MagicMock(
                status_code=200,
                json=lambda: {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "submit_fidelity",
                            "input": {"same_product": False, "issues": ["bad"]},
                        }
                    ],
                    "usage": {"input_tokens": 50, "output_tokens": 25},
                },
            ),
        ]

        client = AnthropicClient(api_key="test-key")
        with patch("apps.ai.anthropic_client.time.sleep"):
            result, usage = client.call(
                model="claude-haiku-4-5-20251001",
                system="S",
                user="U",
                schema=FidelityResult,
                tool_name="submit_fidelity",
            )
        assert result.same_product is False
        assert mock_client.post.call_count == 2

    @patch("apps.ai.anthropic_client.httpx.Client")
    def test_non_retryable_error_raises(self, mock_httpx_class):
        mock_client = MagicMock()
        mock_httpx_class.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=401, text="Unauthorized")

        client = AnthropicClient(api_key="test-key")
        with pytest.raises(AnthropicToolCallError, match="401"):
            client.call(
                model="test",
                system="S",
                user="U",
                schema=FidelityResult,
                tool_name="submit_test",
            )

    @patch("apps.ai.anthropic_client.httpx.Client")
    def test_all_retries_exhausted(self, mock_httpx_class):
        mock_client = MagicMock()
        mock_httpx_class.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=503, text="Unavailable")

        client = AnthropicClient(api_key="test-key")
        with (
            patch("apps.ai.anthropic_client.time.sleep"),
            pytest.raises(AnthropicToolCallError, match="retries exhausted"),
        ):
            client.call(
                model="test",
                system="S",
                user="U",
                schema=FidelityResult,
                tool_name="submit_test",
            )


# ── Prompt rendering tests ────────────────────────────────────────────────


class TestPromptRendering:
    def test_load_research_prompt(self):
        content = load_prompt("research")
        assert "direct-response strategist" in content

    def test_load_missing_prompt_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_prompt")

    def test_render_research_prompt(self):
        system, user = render_prompt(
            "research",
            {
                "locale_name": "Dutch",
                "brand_tone": "warm",
                "niche_hint": "wellness_sleep",
                "import_result_json": '{"title": "Sleep Mask"}',
                "country_hint": "the Netherlands",
            },
        )
        assert "Dutch" in system
        assert "Sleep Mask" in user
        assert "submit_research" in user

    def test_render_copy_prompt(self):
        system, user = render_prompt(
            "copy",
            {
                "locale_name": "German",
                "country_hint": "Germany",
                "brand_name": "TestBrand",
                "brand_tone": "premium",
                "page_type": "pdp",
                "section_order": ["hero", "benefits", "cta"],
                "research_json": "{}",
                "angle_json": "{}",
                "persona_json": "{}",
                "specs_json": "{}",
                "guarantee_policy": "",
                "guardrails": "No medical claims",
            },
        )
        assert "German" in system
        assert "TestBrand" in system or "TestBrand" in user


# ── log_ai_call tests ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLogAiCall:
    def test_logs_call(self, db):
        shop = Shop.objects.create(
            domain="test.myshopify.com",
            shopify_gid="gid://shopify/Shop/1",
            access_token_encrypted=encrypt_token("tok"),
            refresh_token_encrypted=encrypt_token("ref"),
            currency_code="EUR",
        )
        log_ai_call(
            shop=shop,
            step=None,
            purpose="research",
            provider="anthropic",
            model="claude-sonnet-5-5",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=Decimal("0.0105"),
            duration_ms=2000,
            success=True,
        )
        call = AiCall.objects.get(shop=shop)
        assert call.purpose == "research"
        assert call.cost_usd == Decimal("0.0105")
        assert call.success is True

    def test_logs_failed_call(self, db):
        shop = Shop.objects.create(
            domain="fail.myshopify.com",
            shopify_gid="gid://shopify/Shop/2",
            access_token_encrypted=encrypt_token("tok"),
            refresh_token_encrypted=encrypt_token("ref"),
            currency_code="EUR",
        )
        log_ai_call(
            shop=shop,
            step=None,
            purpose="copy",
            provider="anthropic",
            model="claude-sonnet-5-5",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
            duration_ms=100,
            success=False,
        )
        call = AiCall.objects.get(shop=shop)
        assert call.success is False


# ── call_ai integration tests ─────────────────────────────────────────────


@pytest.mark.django_db
class TestCallAi:
    @patch("apps.ai.anthropic_client.AnthropicClient")
    def test_successful_call_ai(self, mock_client_class, db):
        shop = Shop.objects.create(
            domain="test.myshopify.com",
            shopify_gid="gid://shopify/Shop/1",
            access_token_encrypted=encrypt_token("tok"),
            refresh_token_encrypted=encrypt_token("ref"),
            currency_code="EUR",
        )

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.call.return_value = (
            FidelityResult(same_product=True, issues=[]),
            {"input_tokens": 100, "output_tokens": 50},
        )

        result = call_ai(
            shop=shop,
            purpose="fidelity",
            model_key="check",
            system="Test",
            user="Test",
            schema=FidelityResult,
            tool_name="submit_fidelity",
        )
        assert result.same_product is True

        # Verify AiCall was logged
        call = AiCall.objects.get(shop=shop)
        assert call.purpose == "fidelity"
        assert call.provider == "anthropic"

    @patch("apps.ai.anthropic_client.AnthropicClient")
    def test_call_ai_accumulates_step_cost(self, mock_client_class, db):
        shop = Shop.objects.create(
            domain="test.myshopify.com",
            shopify_gid="gid://shopify/Shop/1",
            access_token_encrypted=encrypt_token("tok"),
            refresh_token_encrypted=encrypt_token("ref"),
            currency_code="EUR",
        )
        job = GenerationJob.objects.create(
            shop=shop,
            kind="page",
            page_type="pdp",
            content_locale="nl",
            input={},
            idempotency_key="k1",
        )
        step = JobStep.objects.create(job=job, name="research", status="running")

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.call.return_value = (
            FidelityResult(same_product=True, issues=[]),
            {"input_tokens": 1000, "output_tokens": 500},
        )

        call_ai(
            shop=shop,
            purpose="fidelity",
            model_key="check",
            system="S",
            user="U",
            schema=FidelityResult,
            tool_name="submit_fidelity",
            step=step,
        )

        step.refresh_from_db()
        job.refresh_from_db()
        expected_cost = calculate_cost("claude-haiku-4-5-20251001", 1000, 500)
        assert step.ai_cost_usd == expected_cost
        assert job.ai_cost_usd == expected_cost

    @patch("apps.ai.anthropic_client.AnthropicClient")
    def test_call_ai_logs_failure(self, mock_client_class, db):
        shop = Shop.objects.create(
            domain="test.myshopify.com",
            shopify_gid="gid://shopify/Shop/1",
            access_token_encrypted=encrypt_token("tok"),
            refresh_token_encrypted=encrypt_token("ref"),
            currency_code="EUR",
        )

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.call.side_effect = AnthropicToolCallError("Schema invalid")

        with pytest.raises(AnthropicToolCallError):
            call_ai(
                shop=shop,
                purpose="copy",
                model_key="copy",
                system="S",
                user="U",
                schema=SectionsPayload,
                tool_name="submit_sections",
            )

        call = AiCall.objects.get(shop=shop)
        assert call.success is False
