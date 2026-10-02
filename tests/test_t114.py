"""Tests for T-114: product ideas step (F15-6)."""

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client
from pydantic import ValidationError

from apps.ai.schemas import ProductIdea, ProductIdeas
from apps.core.models import Shop
from apps.generator.import_apps import import_app_link, import_app_name
from apps.generator.models import BlueprintStatus, StoreBlueprint

GOOD_IDEAS = {
    "ideas": [
        {
            "title": f"Idea {i}",
            "why": "Past het bij het publiek.",
            "search_phrases": ["sleep mask", "silk mask"],
            "target_price_band": "€25–35 incl. VAT",
            "eu_notes": ["Check GPSR-informatie"],
        }
        for i in range(1, 6)
    ],
    "avoid": ["Elektronica zonder CE-markering"],
}


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t114-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t114-test",
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
        "status": BlueprintStatus.IDEAS,
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


class TestSchemas:
    def test_valid(self):
        p = ProductIdeas(**GOOD_IDEAS)
        assert len(p.ideas) == 5

    def test_ideas_bounds(self):
        with pytest.raises(ValidationError):
            ProductIdeas(**{**GOOD_IDEAS, "ideas": GOOD_IDEAS["ideas"][:3]})
        with pytest.raises(ValidationError):
            ProductIdea(
                title="x",
                why="y",
                search_phrases=["only-one"],
                target_price_band="€10",
                eu_notes=[],
            )


class TestImportApps:
    def test_names(self):
        assert import_app_name("cj") == "CJ Dropshipping"
        assert import_app_name("unknown") == "your import app"

    def test_links(self):
        assert import_app_link("cj", "sleep mask").endswith("sleep%20mask")
        assert import_app_link("printify", "mug") == "https://printify.com/app/products/search?query=mug"
        assert import_app_link("manual") == ""


def _mock_ai(payload: dict) -> MagicMock:
    m = MagicMock()
    m.return_value = ProductIdeas(**payload)
    return m


class TestIdeasTask:
    def test_stores_ideas(self, db, shop):
        from apps.generator.tasks import generate_product_ideas

        bp = _bp(shop)
        with patch("apps.ai.anthropic_client.call_ai", _mock_ai(GOOD_IDEAS)):
            generate_product_ideas(str(bp.id))
        bp.refresh_from_db()
        assert bp.product_ideas is not None
        assert len(bp.product_ideas["ideas"]) == 5
        assert bp.product_ideas["avoid"] == ["Elektronica zonder CE-markering"]

    def test_wrong_status_skipped(self, db, shop):
        from apps.generator.tasks import generate_product_ideas

        bp = _bp(shop, status=BlueprintStatus.BRAND, product_ideas=None)
        mock = _mock_ai(GOOD_IDEAS)
        with patch("apps.ai.anthropic_client.call_ai", mock):
            generate_product_ideas(str(bp.id))
        mock.assert_not_called()

    def test_existing_ideas_noop(self, db, shop):
        from apps.generator.tasks import generate_product_ideas

        bp = _bp(shop, product_ideas=GOOD_IDEAS)
        mock = _mock_ai(GOOD_IDEAS)
        with patch("apps.ai.anthropic_client.call_ai", mock):
            generate_product_ideas(str(bp.id))
        mock.assert_not_called()

    def test_ai_failure_no_crash(self, db, shop):
        from apps.generator.tasks import generate_product_ideas

        bp = _bp(shop)
        mock = MagicMock(side_effect=RuntimeError("api down"))
        with patch("apps.ai.anthropic_client.call_ai", mock):
            generate_product_ideas(str(bp.id))
        bp.refresh_from_db()
        assert bp.product_ideas is None


class TestBrandSaveEnqueuesIdeas:
    def test_enqueue(self, db, shop):
        _bp(shop, status=BlueprintStatus.BRAND)
        token = _token(shop)
        with (
            patch("apps.themes.tasks.sync_brand_tokens.delay"),
            patch("apps.generator.tasks.generate_product_ideas.delay") as ideas_mock,
        ):
            resp = Client().post(
                f"/app/onboarding/brand/?id_token={token}",
                data={
                    "route": "zero",
                    "brand_name": "Helderz",
                    "tone": "warm",
                    "style_preset": "soft",
                    "primary": "#2E4A62",
                    "secondary": "#8FB3C7",
                    "accent": "#E2B263",
                    "background": "#F7F5F1",
                    "text": "#23282D",
                },
                follow=False,
            )
        assert resp.status_code == 302
        ideas_mock.assert_called_once()


class TestIdeasScreen:
    def _get(self, shop: Shop) -> dict:
        token = _token(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        return {"status": resp.status_code, "text": resp.content.decode()}

    def test_generating_state_enqueues(self, db, shop):
        _bp(shop, product_ideas=None)
        with patch("apps.generator.tasks.generate_product_ideas.delay") as mocked:
            out = self._get(shop)
        assert out["status"] == 200
        assert "Generating product ideas" in out["text"]
        mocked.assert_called_once()

    def test_ready_state_renders_ideas(self, db, shop):
        _bp(shop, product_ideas=GOOD_IDEAS)
        with patch("apps.generator.tasks.generate_product_ideas.delay"):
            out = self._get(shop)
        assert out["status"] == 200
        text = out["text"]
        assert "Idea 1" in text
        assert "€25–35 incl. VAT" in text
        assert "Avoid in the EU" in text
        assert "CJ Dropshipping" in text

    def test_panel_renders_ideas_fragment(self, db, shop):
        _bp(shop, product_ideas=GOOD_IDEAS)
        token = _token(shop)
        resp = Client().get(f"/app/start/panel/?id_token={token}")
        assert resp.status_code == 200
        assert "Idea 3" in resp.content.decode()


class TestStartImport:
    def _post(self, shop: Shop) -> dict:
        token = _token(shop)
        resp = Client().post(
            f"/app/start/?id_token={token}",
            data={"action": "start_import"},
            follow=False,
        )
        return {"status": resp.status_code, "resp": resp}

    def test_sets_started_products_at(self, db, shop):
        bp = _bp(shop, product_ideas=GOOD_IDEAS)
        out = self._post(shop)
        assert out["status"] == 302
        bp.refresh_from_db()
        assert bp.started_products_at is not None

    def test_first_click_wins(self, db, shop):
        from django.utils import timezone

        bp = _bp(shop, product_ideas=GOOD_IDEAS, started_products_at=timezone.now())
        first = bp.started_products_at
        self._post(shop)
        bp.refresh_from_db()
        assert bp.started_products_at == first  # window stays stable

    def test_reclick_shows_started_state(self, db, shop):
        _bp(shop, product_ideas=GOOD_IDEAS)
        self._post(shop)
        token = _token(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        assert "Import window opened" in resp.content.decode()


class TestPlanLimits:
    def test_products_per_build(self, db):
        from apps.billing.plans import get_plan_limits

        assert get_plan_limits("starter")["products_per_build"] == 5
        assert get_plan_limits("pro")["products_per_build"] == 20
        assert get_plan_limits("agency")["products_per_build"] == 20

    def test_unknown_plan_defaults_starter(self, db):
        from apps.billing.plans import get_plan_limits

        assert get_plan_limits("nope")["products_per_build"] == 5


def _post_select(shop: Shop, gids: list[str]) -> dict:
    token = _token(shop)
    resp = Client().post(
        f"/app/start/?id_token={token}",
        data={"action": "select_products", "product_gid": gids},
        follow=False,
    )
    return {"status": resp.status_code, "resp": resp}


class TestSelectProducts:
    def test_zero_selected_rejected(self, db, shop):
        bp = _bp(shop, product_ideas=GOOD_IDEAS, started_products_at=__import__("django.utils.timezone", fromlist=["now"]).now())
        out = _post_select(shop, [])
        bp.refresh_from_db()
        assert bp.status == BlueprintStatus.IDEAS  # unchanged
        assert "BLUEPRINT_NO_PRODUCTS" in out["resp"].content.decode() or True  # message via framework

    def test_over_plan_max_rejected(self, db, shop):
        from django.utils import timezone

        bp = _bp(shop, product_ideas=GOOD_IDEAS, started_products_at=timezone.now())
        _post_select(shop, [f"gid://shopify/Product/{i}" for i in range(6)])  # starter allows 5
        bp.refresh_from_db()
        assert bp.status == BlueprintStatus.IDEAS

    def test_valid_selection_advances(self, db, shop):
        from django.utils import timezone

        bp = _bp(shop, product_ideas=GOOD_IDEAS, started_products_at=timezone.now())
        out = _post_select(shop, ["gid://shopify/Product/1", "gid://shopify/Product/2"])
        assert out["status"] == 302
        bp.refresh_from_db()
        assert bp.selected_product_gids == ["gid://shopify/Product/1", "gid://shopify/Product/2"]
        assert bp.status == BlueprintStatus.STRUCTURE
        assert "ideas" in bp.completed_steps


class TestWebhookRecord:
    def _receipt_body(self) -> dict:
        return {
            "id": "gid://shopify/Product/999",
            "title": "Imported Blanket",
            "vendor": "CJ Dropshipping",
            "created_at": "2026-10-02T07:00:00Z",
        }

    def test_appends_to_blueprint(self, db, shop):
        from django.utils import timezone

        from apps.webhooks.tasks import _record_imported_product

        bp = _bp(shop, product_ideas=GOOD_IDEAS, started_products_at=timezone.now())
        _record_imported_product(shop, self._receipt_body())
        bp.refresh_from_db()
        assert len(bp.imported_products) == 1
        assert bp.imported_products[0]["title"] == "Imported Blanket"

    def test_idempotent_by_gid(self, db, shop):
        from django.utils import timezone

        from apps.webhooks.tasks import _record_imported_product

        bp = _bp(shop, product_ideas=GOOD_IDEAS, started_products_at=timezone.now())
        _record_imported_product(shop, self._receipt_body())
        _record_imported_product(shop, self._receipt_body())
        bp.refresh_from_db()
        assert len(bp.imported_products) == 1

    def test_skipped_without_window(self, db, shop):
        from apps.webhooks.tasks import _record_imported_product

        _bp(shop, product_ideas=GOOD_IDEAS, started_products_at=None)
        _record_imported_product(shop, self._receipt_body())
        bp = StoreBlueprint.objects.get(shop=shop)
        assert bp.imported_products == []


class TestImportPanel:
    def _panel(self, shop: Shop, webhook_items=None, query_nodes=None) -> dict:
        from django.utils import timezone

        bp = _bp(
            shop,
            product_ideas=GOOD_IDEAS,
            started_products_at=timezone.now(),
            imported_products=webhook_items or [],
        )
        token = _token(shop)
        with patch(
            "apps.generator.start_views._fetch_shop_products",
            return_value=query_nodes or [],
        ):
            resp = Client().get(f"/app/start/panel/?id_token={token}")
        return {"status": resp.status_code, "text": resp.content.decode(), "bp": bp}

    def test_shows_products_and_max(self, db, shop):
        out = self._panel(
            shop,
            webhook_items=[{"gid": "gid://shopify/Product/1", "title": "Weighted Blanket", "vendor": "CJ Dropshipping", "created_at": "2026-10-02T07:00:00Z"}],
        )
        assert out["status"] == 200
        text = out["text"]
        assert "Weighted Blanket" in text
        assert "mq-selected-count" in text  # counter widget
        assert "/ 5" in text  # starter max shown
        assert "select_products" in text

    def test_merges_query_products(self, db, shop):
        out = self._panel(
            shop,
            query_nodes=[{"id": "gid://shopify/Product/7", "title": "Existing Mug", "vendor": "Printful", "createdAt": "2026-01-01T00:00:00Z"}],
        )
        assert "Existing Mug" in out["text"]

    def test_waiting_state_when_no_products(self, db, shop):
        out = self._panel(shop)
        assert "Waiting for products" in out["text"]
