"""Tests for T-113: brand step — niche_brand proposal + BrandKit prefill (F15-5)."""

from unittest.mock import MagicMock, patch

import jwt as pyjwt
from pydantic import ValidationError
import pytest
from django.conf import settings
from django.test import Client

from apps.ai.schemas import BrandProposal
from apps.core.models import Shop
from apps.generator.models import BlueprintStatus, StoreBlueprint
from apps.themes.models import BrandKit

GOOD_PROPOSAL = {
    "tone": "warm",
    "style_preset": "soft",
    "palette": {
        "primary": "#2E4A62",
        "secondary": "#8FB3C7",
        "accent": "#E2B263",
        "background": "#F7F5F1",
        "text": "#23282D",
        "rationale": "Calm blues with a warm accent fit the audience.",
    },
    "font_heading": "lora",
    "font_body": "inter",
    "tagline": "Rustiger slapen, elke nacht",
    "rationale": "Warm, calm brand for sleep-wellness buyers.",
}


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t113-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t113-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        onboarding_step="brand",
        onboarding_route="zero",
    )


def _token(shop: Shop) -> str:
    return pyjwt.encode(
        {
            "iss": f"https://{shop.domain}/admin",
            "dest": f"https://{shop.domain}",
            "aud": settings.SHOPIFY_API_KEY,
            "sub": "12345",
            "exp": 9999999999,
            "nbf": 1000000000,
        },
        settings.SHOPIFY_API_SECRET,
        algorithm="HS256",
    )


def _bp(shop: Shop, **overrides) -> StoreBlueprint:
    defaults = {
        "shop": shop,
        "onboarding_route": "zero",
        "status": BlueprintStatus.BRAND,
        "description": "Sleep wellness products for people who struggle to fall asleep.",
        "markets": ["NL"],
        "content_locales": ["nl"],
        "audience": "adults",
        "price_level": "mid",
        "import_app": "cj",
        "brand_name": "Helderz",
        "brand_slug": "helderz",
    }
    defaults.update(overrides)
    return StoreBlueprint.objects.create(**defaults)


class TestBrandProposalSchema:
    def test_valid(self):
        p = BrandProposal(**GOOD_PROPOSAL)
        assert p.tone == "warm"

    def test_tagline_too_long(self):
        with pytest.raises(ValidationError):
            BrandProposal(**{**GOOD_PROPOSAL, "tagline": "x" * 61})

    def test_invalid_tone(self):
        with pytest.raises(ValidationError):
            BrandProposal(**{**GOOD_PROPOSAL, "tone": "angry"})


def _mock_ai(proposal: dict) -> MagicMock:
    m = MagicMock()
    p = BrandProposal(**proposal)
    m.return_value = (p, {"input_tokens": 10, "output_tokens": 20})
    return m


class TestBrandProposalTask:
    def test_stores_proposal(self, db, shop):
        from apps.generator.tasks import generate_brand_proposal

        bp = _bp(shop)
        with patch("apps.ai.anthropic_client.call_ai", _mock_ai(GOOD_PROPOSAL)):
            generate_brand_proposal(str(bp.id))
        bp.refresh_from_db()
        assert bp.brand_proposal is not None
        assert bp.brand_proposal["tone"] == "warm"
        assert bp.brand_proposal["palette"]["text"] == "#23282D"

    def test_invalid_font_key_corrected_to_inherit(self, db, shop):
        from apps.generator.tasks import generate_brand_proposal

        bp = _bp(shop)
        bad = {**GOOD_PROPOSAL, "font_heading": "comic-sans-not-real"}
        with patch("apps.ai.anthropic_client.call_ai", _mock_ai(bad)):
            generate_brand_proposal(str(bp.id))
        bp.refresh_from_db()
        assert bp.brand_proposal["font_heading"] == ""  # inherit theme font

    def test_low_contrast_text_corrected(self, db, shop):
        from apps.generator.tasks import generate_brand_proposal

        bp = _bp(shop)
        bad = {**GOOD_PROPOSAL, "palette": {**GOOD_PROPOSAL["palette"], "text": "#CCCCCC", "background": "#FFFFFF"}}
        with patch("apps.ai.anthropic_client.call_ai", _mock_ai(bad)):
            generate_brand_proposal(str(bp.id))
        bp.refresh_from_db()
        # CCCC on FFFFFF fails 4.5:1 → corrected darker, never stored as-is
        assert bp.brand_proposal["palette"]["text"] != "#CCCCCC"

    def test_wrong_status_skipped(self, db, shop):
        from apps.generator.tasks import generate_brand_proposal

        bp = _bp(shop, status=BlueprintStatus.NAMES, brand_proposal=None)
        mock = _mock_ai(GOOD_PROPOSAL)
        with patch("apps.ai.anthropic_client.call_ai", mock):
            generate_brand_proposal(str(bp.id))
        mock.assert_not_called()

    def test_existing_proposal_noop(self, db, shop):
        from apps.generator.tasks import generate_brand_proposal

        bp = _bp(shop, brand_proposal={"tone": "warm"})
        mock = _mock_ai(GOOD_PROPOSAL)
        with patch("apps.ai.anthropic_client.call_ai", mock):
            generate_brand_proposal(str(bp.id))
        mock.assert_not_called()

    def test_ai_failure_no_crash(self, db, shop):
        from apps.generator.tasks import generate_brand_proposal

        bp = _bp(shop)
        mock = MagicMock(side_effect=RuntimeError("api down"))
        with patch("apps.ai.anthropic_client.call_ai", mock):
            generate_brand_proposal(str(bp.id))
        bp.refresh_from_db()
        assert bp.brand_proposal is None


class TestPickEnqueuesBrandTask:
    def test_pick_enqueues(self, db, shop):
        _bp(shop, status=BlueprintStatus.NAMES, brand_name="", name_suggestions=[
            {"name": "Helderz", "rationale": "fits", "pronunciation_ok": ["nl"], "domain_status": "likely_free"}
        ])
        token = _token(shop)
        with patch("apps.generator.start_views.generate_brand_proposal.delay") as mocked:
            resp = Client().post(
                f"/app/start/?id_token={token}",
                data={"action": "pick", "pick_index": "0"},
                follow=False,
            )
        assert resp.status_code == 302
        mocked.assert_called_once()


class TestBrandStepScreen:
    def _get(self, shop: Shop, follow: bool = False) -> dict:
        token = _token(shop)
        resp = Client().get(f"/app/onboarding/brand/?id_token={token}", follow=follow)
        return {"status": resp.status_code, "text": resp.content.decode(), "resp": resp}

    def test_generating_state_enqueues(self, db, shop):
        _bp(shop, brand_proposal=None)
        with patch("apps.generator.tasks.generate_brand_proposal.delay") as mocked:
            out = self._get(shop)
        assert out["status"] == 200
        assert "Designing your brand" in out["text"]
        mocked.assert_called_once()

    def test_proposal_prefills_form(self, db, shop):
        _bp(shop, brand_proposal=GOOD_PROPOSAL)
        with patch("apps.generator.tasks.generate_brand_proposal.delay"):
            out = self._get(shop)
        assert out["status"] == 200
        text = out["text"]
        assert "Your brand proposal" in text
        assert 'value="#2E4A62"' in text  # primary pre-filled
        assert 'value="Rustiger slapen, elke nacht"' in text  # tagline
        assert 'value="lora"' in text  # font heading
        assert "selected" in text  # tone/preset preselected

    def test_ideas_status_redirects_to_wizard(self, db, shop):
        _bp(shop, status=BlueprintStatus.IDEAS)
        with patch("apps.generator.tasks.generate_brand_proposal.delay") as mocked:
            out = self._get(shop)
        assert out["status"] == 302
        assert "/app/start/" in out["resp"]["Location"]
        mocked.assert_not_called()

    def test_existing_route_unchanged(self, db, shop):
        shop.onboarding_route = "existing"
        shop.save(update_fields=["onboarding_route"])
        out = self._get(shop)
        assert out["status"] == 200
        assert "I already have a brand" in out["text"] or "Your brand" in out["text"]


class TestBrandSave:
    def _post(self, shop: Shop, data: dict) -> dict:
        token = _token(shop)
        resp = Client().post(f"/app/onboarding/brand/?id_token={token}", data=data, follow=False)
        return {"status": resp.status_code, "resp": resp, "text": resp.content.decode()}

    def test_save_zero_route(self, db, shop):
        bp = _bp(shop, brand_proposal=GOOD_PROPOSAL)
        with patch("apps.themes.tasks.sync_brand_tokens.delay") as token_mock:
            out = self._post(
                shop,
                {
                    "route": "zero",
                    "brand_name": "Helderz",
                    "tone": "warm",
                    "style_preset": "soft",
                    "primary": "#2E4A62",
                    "secondary": "#8FB3C7",
                    "accent": "#E2B263",
                    "background": "#F7F5F1",
                    "text": "#23282D",
                    "font_heading": "lora",
                    "font_body": "inter",
                    "tagline": "Rustiger slapen, elke nacht",
                },
            )
        assert out["status"] == 302
        assert "/app/start/" in out["resp"]["Location"]
        bk = BrandKit.objects.get(shop=shop)
        assert bk.brand_name == "Helderz"
        assert bk.tagline == "Rustiger slapen, elke nacht"
        assert bk.palette["primary"] == "#2E4A62"
        bp.refresh_from_db()
        assert bp.status == BlueprintStatus.IDEAS
        assert "brand" in bp.completed_steps
        assert bp.palette["primary"] == "#2E4A62"
        token_mock.assert_called_once()

    def test_save_applies_contrast_correction(self, db, shop):
        _bp(shop, brand_proposal=GOOD_PROPOSAL)
        with patch("apps.themes.tasks.sync_brand_tokens.delay"):
            self._post(
                shop,
                {
                    "route": "zero",
                    "brand_name": "Helderz",
                    "tone": "warm",
                    "style_preset": "soft",
                    "primary": "#2E4A62",
                    "secondary": "#8FB3C7",
                    "accent": "#E2B263",
                    "background": "#FFFFFF",
                    "text": "#DDDDDD",  # fails 4.5:1 on white
                    "font_heading": "lora",
                    "font_body": "inter",
                },
            )
        bk = BrandKit.objects.get(shop=shop)
        assert bk.palette["text"] != "#DDDDDD"  # corrected, never stored as-is


class TestSyncBrandTokens:
    def test_calls_sync(self, db, shop):
        from apps.themes.models import BrandKit
        from apps.themes.tasks import sync_brand_tokens

        BrandKit.objects.create(
            shop=shop,
            brand_name="Helderz",
            tone="warm",
            palette=GOOD_PROPOSAL["palette"],
            style_preset="soft",
            font_heading="lora",
            font_body="inter",
        )
        with (
            patch("apps.themes.tokens.sync_tokens_to_metafield", return_value=True) as sync,
            patch("apps.core.crypto.decrypt_token", return_value="shpat_test"),
        ):
            sync_brand_tokens(str(shop.id))
        sync.assert_called_once()

    def test_no_brandkit_noop(self, db, shop):
        from apps.themes.tasks import sync_brand_tokens

        with patch("apps.themes.tokens.sync_tokens_to_metafield") as sync:
            sync_brand_tokens(str(shop.id))
        sync.assert_not_called()
