"""Tests for T-116: standard page types faq/shipping/returns (12 §3, F15-16, F18-10)."""

from unittest.mock import patch

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.core.models import BusinessDetails, Shop
from apps.generator.models import BlueprintStatus, PageType, StoreBlueprint

G1 = "gid://shopify/Product/111"


def _token(shop: Shop) -> str:
    return pyjwt.encode(
        {
            "iss": f"https://{shop.domain}/admin",
            "dest": f"https://{shop.domain}",
            "aud": settings.SHOPIFY_API_KEY,
            "sub": "12345",
            "exp": 9999999999,
            "nbf": 1,
        },
        settings.SHOPIFY_API_SECRET,
        algorithm="HS256",
    )


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t116-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t116-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        onboarding_step="brand",
        onboarding_route="zero",
    )


def _bp(shop: Shop, **overrides) -> StoreBlueprint:
    defaults = {
        "shop": shop,
        "status": BlueprintStatus.BUILDING,
        "onboarding_route": "zero",
        "brand_name": "Helderz",
        "selected_product_gids": [G1],
        "store_structure": {
            "collections": [{"title": "Alles", "description": "d", "product_gids": [G1]}],
            "menu": [
                {"title": "Home", "target": "frontpage", "ref": None},
                {"title": "Alles", "target": "collection", "ref": "Alles"},
                {"title": "Verzending", "target": "page", "ref": "shipping"},
                {"title": "Retour", "target": "page", "ref": "returns"},
            ],
            "pages": ["about", "faq", "shipping", "returns"],
        },
    }
    defaults.update(overrides)
    return StoreBlueprint.objects.create(**defaults)


AI_PAGES = {
    "pages": [
        {
            "page_type": "faq",
            "title": "Veelgestelde vragen",
            "intro": "Antwoorden op de meest gestelde vragen over onze producten.",
            "faq_items": [
                {"question": "Hoe lang duurt de levering?", "answer": "Zie de verzendpagina voor de actuele levertijden."},
                {"question": "Kan ik ruilen?", "answer": "Bekijk de retourpagina voor de voorwaarden."},
            ],
        },
        {
            "page_type": "shipping",
            "title": "Verzending",
            "intro": "Alles over de levering van je bestelling.",
            "faq_items": [{"question": "Wat kost verzenden?", "answer": "De kosten staan bij de levertijden hieronder."}],
        },
        {
            "page_type": "returns",
            "title": "Retourneren",
            "intro": "Je hebt 14 dagen bedenktijd.",
            "faq_items": [{"question": "Hoe retourneer ik?", "answer": "Vraag een retour aan via het behoudsformulier."}],
        },
    ]
}


def _mock_ai(payload):
    from apps.ai.schemas import StandardPages

    def _fn(**kwargs):
        return payload if hasattr(payload, "pages") else StandardPages(**payload)

    return _fn


def _profile(shop: Shop, **overrides):
    from apps.compliance.models import DeliveryProfile

    defaults = {
        "shop": shop,
        "source_app": "cj",
        "ship_from_country": "CN",
        "processing_days_min": 2,
        "processing_days_max": 4,
        "transit_days": {"NL": [5, 9], "DE": [6, 10]},
        "shipping_cost": {"NL": {"amount": "4.95", "free_from": "40.00"}},
    }
    defaults.update(overrides)
    return DeliveryProfile.objects.create(**defaults)


class TestPageTypeAndSchemas:
    def test_page_types_exist(self, db):
        for value in ("faq", "shipping", "returns"):
            assert value in PageType.values

    def test_standard_pages_schema(self, db):
        from apps.ai.schemas import StandardPages

        model = StandardPages(**AI_PAGES)
        assert len(model.pages) == 3

    def test_page_type_literal_enforced(self, db):
        from pydantic import ValidationError

        from apps.ai.schemas import StandardPages

        bad = {"pages": [{**AI_PAGES["pages"][0], "page_type": "legal"}]}
        with pytest.raises(ValidationError):
            StandardPages(**bad)


class TestFactSections:
    def test_shipping_without_profile_lists_missing(self, db, shop):
        from apps.generator.standard_pages import build_fact_sections

        sections, missing = build_fact_sections(shop, "shipping")
        assert "Delivery times missing" in str(sections)
        assert "delivery_profile" in missing

    def test_shipping_with_profile_renders_days_and_costs(self, db, shop):
        from apps.generator.standard_pages import build_fact_sections

        _profile(shop)
        sections, missing = build_fact_sections(shop, "shipping")
        text = str(sections)
        assert missing == []
        assert "CN" in text
        assert "5" in text and "9" in text
        assert "4.95" in text
        assert "40.00" in text

    def test_returns_without_business_details_lists_missing(self, db, shop):
        from apps.generator.standard_pages import build_fact_sections

        sections, missing = build_fact_sections(shop, "returns")
        assert missing
        assert "legal_name" in missing

    def test_returns_with_business_details_contains_address(self, db, shop):
        from apps.generator.standard_pages import build_fact_sections

        BusinessDetails.objects.create(
            shop=shop,
            legal_name="Helderz B.V.",
            street="Dorpsstraat 1",
            postal_code="6100AB",
            city="Venlo",
            country_code="NL",
            return_address_same=True,
        )
        sections, missing = build_fact_sections(shop, "returns")
        assert missing == []
        text = str(sections)
        assert "Helderz B.V." in text
        assert "6100AB" in text
        assert "/pages/withdrawal" in text


class TestGenerateStandardPages:
    def _run(self, bp: StoreBlueprint, ai_payload=None, with_profile=True, with_business=True):
        if with_profile:
            _profile(bp.shop)
        if with_business:
            BusinessDetails.objects.create(
                shop=bp.shop,
                legal_name="Helderz B.V.",
                street="Dorpsstraat 1",
                postal_code="6100AB",
                city="Venlo",
                country_code="NL",
                return_address_same=True,
            )
        from apps.generator.tasks import generate_standard_pages

        payload = ai_payload or AI_PAGES
        with (
            patch("apps.ai.anthropic_client.call_ai", _mock_ai(payload)),
            patch("apps.generator.tasks._standard_pages_facts", return_value={"delivery": [], "business": {}}),
        ):
            generate_standard_pages(str(bp.id))
        bp.refresh_from_db()
        return bp

    def test_happy_path(self, db, shop):
        bp = self._run(_bp(shop))
        assert bp.standard_pages is not None
        assert {"faq", "shipping", "returns"} <= set(bp.standard_pages.keys())
        # "about" was requested by the structure but not in the AI payload
        assert bp.standard_pages["about"]["warnings"] == ["not_generated"]

    def test_shipping_sections_structure(self, db, shop):
        bp = self._run(_bp(shop))
        types = [s["type"] for s in bp.standard_pages["shipping"]["sections"]]
        assert types == ["rich_text", "rich_text", "faq"]

    def test_returns_sections_structure(self, db, shop):
        bp = self._run(_bp(shop))
        types = [s["type"] for s in bp.standard_pages["returns"]["sections"]]
        assert types[:2] == ["rich_text", "rich_text"]
        assert "faq" in types

    def test_ai_numbers_repaired_once(self, db, shop):
        leaky = {
            "pages": [
                {
                    "page_type": "faq",
                    "title": "FAQ",
                    "intro": "We leveren binnen 3 dagen.",
                    "faq_items": [{"question": "Snel?", "answer": "Ja, 3 dagen."}],
                }
            ]
        }
        bp = _bp(shop)
        from apps.generator.tasks import generate_standard_pages

        with (
            patch("apps.ai.anthropic_client.call_ai", side_effect=[_as_pages(leaky), _as_pages(AI_PAGES)]) as ai,
            patch("apps.generator.tasks._standard_pages_facts", return_value={"delivery": [], "business": {}}),
        ):
            generate_standard_pages(str(bp.id))
        bp.refresh_from_db()
        assert ai.call_count == 2
        assert "faq" in bp.standard_pages

    def test_ai_numbers_kept_with_flag_after_repair(self, db, shop):
        leaky = {
            "pages": [
                {
                    "page_type": "faq",
                    "title": "FAQ",
                    "intro": "We leveren binnen 3 dagen.",
                    "faq_items": [{"question": "Snel?", "answer": "Ja, 3 dagen."}],
                }
            ]
        }
        bp = _bp(shop)
        from apps.generator.tasks import generate_standard_pages

        with (
            patch("apps.ai.anthropic_client.call_ai", side_effect=[_as_pages(leaky), _as_pages(leaky)]),
            patch("apps.generator.tasks._standard_pages_facts", return_value={"delivery": [], "business": {}}),
        ):
            generate_standard_pages(str(bp.id))
        bp.refresh_from_db()
        assert "verify_numbers" in (bp.standard_pages.get("faq") or {}).get("warnings", [])

    def test_skips_when_not_building(self, db, shop):
        bp = _bp(shop, status=BlueprintStatus.STRUCTURE)
        from apps.generator.tasks import generate_standard_pages

        with patch("apps.ai.anthropic_client.call_ai") as ai:
            generate_standard_pages(str(bp.id))
        ai.assert_not_called()


def _as_pages(payload):
    from apps.ai.schemas import StandardPages

    return payload if hasattr(payload, "pages") else StandardPages(**payload)


class TestWiringAndScreens:
    def test_confirm_enqueues_standard_pages(self, db, shop):
        bp = _bp(shop, status=BlueprintStatus.STRUCTURE)
        token = _token(shop)
        with patch("apps.generator.start_views.generate_standard_pages") as gen:
            Client().post(
                f"/app/start/?id_token={token}",
                data={"action": "structure_confirm"},
                follow=False,
            )
        gen.delay.assert_called_once()
        bp.refresh_from_db()
        assert bp.status == BlueprintStatus.BUILDING

    def test_building_panel_shows_pages(self, db, shop):
        _bp(
            shop,
            standard_pages={
                "faq": {"title": "FAQ", "sections": [], "warnings": []},
                "shipping": {"title": "Verzending", "sections": [], "warnings": ["Delivery times missing"]},
            },
        )
        token = _token(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        text = resp.content.decode()
        assert resp.status_code == 200
        assert "Verzending" in text
        assert "Delivery times missing" in text
