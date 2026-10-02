"""Tests for T-115: store structure proposal + editable tree (F15-8)."""

from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.core.models import Shop
from apps.generator.models import BlueprintStatus, StoreBlueprint


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t115-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t115-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        onboarding_step="brand",
        onboarding_route="zero",
    )


G1 = "gid://shopify/Product/111"
G2 = "gid://shopify/Product/222"


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


def _bp(shop: Shop, **overrides) -> StoreBlueprint:
    defaults = {
        "shop": shop,
        "status": BlueprintStatus.STRUCTURE,
        "onboarding_route": "zero",
        "brand_name": "Helderz",
        "selected_product_gids": [G1, G2],
    }
    defaults.update(overrides)
    return StoreBlueprint.objects.create(**defaults)


def _post(shop: Shop, data: dict) -> dict:
    token = _token(shop)
    resp = Client().post(
        f"/app/start/?id_token={token}", data=data, follow=False
    )
    return {"status": resp.status_code, "resp": resp, "text": resp.content.decode()}


VALID_STRUCTURE = {
    "collections": [
        {"title": "Slaapmaskers", "description": "Maskers voor rustige nachten.", "product_gids": [G1]},
        {"title": "Rituelen", "description": "Accessoires voor het avondritueel.", "product_gids": [G2]},
    ],
    "menu": [
        {"title": "Home", "target": "frontpage", "ref": None},
        {"title": "Slaapmaskers", "target": "collection", "ref": "Slaapmaskers"},
        {"title": "Rituelen", "target": "collection", "ref": "Rituelen"},
        {"title": "Verzending", "target": "page", "ref": "shipping"},
        {"title": "Retourneren", "target": "page", "ref": "returns"},
    ],
    "pages": ["about", "faq", "shipping", "returns"],
}


def _as_model(payload):
    from apps.ai.schemas import StoreStructure

    return payload if hasattr(payload, "collections") else StoreStructure(**payload)


def _mock_ai(payload):
    def _fn(**kwargs):
        return _as_model(payload)

    return _fn


def _products_payload():
    return [
        {"id": G1, "title": "Sleep Mask", "productType": "sleep", "tags": "sleep", "price": "24.95"},
        {"id": G2, "title": "Evening Candle", "productType": "home", "tags": "ritual", "price": "19.95"},
    ]


class TestStoreStructureSchema:
    def test_valid(self, db):
        from apps.ai.schemas import StoreStructure

        model = StoreStructure(**VALID_STRUCTURE)
        assert len(model.collections) == 2
        assert model.pages[0] == "about"

    def test_page_literals_enforced(self, db):
        from pydantic import ValidationError

        from apps.ai.schemas import StoreStructure

        bad = {**VALID_STRUCTURE, "pages": ["about", "legal"]}
        with pytest.raises(ValidationError):
            StoreStructure(**bad)


class TestGenerateStoreStructure:
    def _run(self, bp: StoreBlueprint, ai_payload):
        from apps.generator import tasks

        with (
            patch("apps.ai.anthropic_client.call_ai", _mock_ai(ai_payload)),
            patch.object(tasks, "_fetch_products_by_ids", return_value=_products_payload()),
        ):
            tasks.generate_store_structure(str(bp.id))
        bp.refresh_from_db()
        return bp

    def test_happy_path(self, db, shop):
        bp = _bp(shop)
        bp = self._run(bp, VALID_STRUCTURE)
        assert bp.store_structure is not None
        assert bp.store_structure["collections"][0]["title"] == "Slaapmaskers"
        assert bp.structure_error == ""

    def test_invalid_gid_repaired_once(self, db, shop):
        bad = {**VALID_STRUCTURE, "collections": [{"title": "X", "description": "d", "product_gids": ["gid://shopify/Product/999"]}]}
        bp = _bp(shop)
        from apps.generator.tasks import generate_store_structure

        with (
            patch("apps.ai.anthropic_client.call_ai", side_effect=[_as_model(bad), _as_model(VALID_STRUCTURE)]) as ai,
            patch("apps.generator.tasks._fetch_products_by_ids", return_value=_products_payload()),
        ):
            generate_store_structure(str(bp.id))
        bp.refresh_from_db()
        assert ai.call_count == 2
        assert bp.store_structure is not None
        assert bp.structure_error == ""

    def test_repair_fails_merchant_message(self, db, shop):
        bad = {**VALID_STRUCTURE, "collections": [{"title": "X", "description": "d", "product_gids": ["gid://shopify/Product/999"]}]}
        bp = _bp(shop)
        with (
            patch("apps.ai.anthropic_client.call_ai", side_effect=[_as_model(bad), _as_model(bad)]),
            patch("apps.generator.tasks._fetch_products_by_ids", return_value=_products_payload()),
        ):
            from apps.generator.tasks import generate_store_structure

            generate_store_structure(str(bp.id))
        bp.refresh_from_db()
        assert bp.store_structure is None
        assert "not part of your product selection" in bp.structure_error
        assert bp.status == BlueprintStatus.STRUCTURE

    def test_ai_exception_sets_message(self, db, shop):
        bp = _bp(shop)
        with (
            patch("apps.ai.anthropic_client.call_ai", side_effect=RuntimeError("down")),
            patch("apps.generator.tasks._fetch_products_by_ids", return_value=_products_payload()),
        ):
            from apps.generator.tasks import generate_store_structure

            generate_store_structure(str(bp.id))
        bp.refresh_from_db()
        assert bp.structure_error != ""
        assert bp.store_structure is None

    def test_skips_when_not_structure_state(self, db, shop):
        bp = _bp(shop, status=BlueprintStatus.IDEAS)
        with patch("apps.ai.anthropic_client.call_ai") as ai:
            from apps.generator.tasks import generate_store_structure

            generate_store_structure(str(bp.id))
        ai.assert_not_called()

    def test_fetch_products_by_ids_maps_fields(self, db, shop):
        from apps.generator.tasks import _fetch_products_by_ids

        client = MagicMock()
        client.execute.return_value = {
            "nodes": [
                {"id": G1, "title": "Sleep Mask", "productType": "sleep", "tags": "a,b", "priceRange": {"minVariantPrice": {"amount": "24.95"}}},
            ]
        }
        with (
            patch("apps.core.crypto.decrypt_token", return_value="shpat_test"),
            patch("apps.core.shopify_client.ShopifyGraphQLClient", return_value=client),
        ):
            rows = _fetch_products_by_ids(shop, [G1])
        assert rows[0]["price"] == "24.95"


class TestStructureScreen:
    def _get(self, shop: Shop, bp: StoreBlueprint) -> dict:
        token = _token(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        return {"status": resp.status_code, "text": resp.content.decode()}

    def test_generating_state(self, db, shop):
        bp = _bp(shop)
        out = self._get(shop, bp)
        assert out["status"] == 200
        assert "Generating store structure" in out["text"]

    def test_proposal_tree_shown(self, db, shop):
        bp = _bp(shop, store_structure=VALID_STRUCTURE)
        out = self._get(shop, bp)
        assert "Slaapmaskers" in out["text"]
        assert "structure_rename" in out["text"]
        assert "Retourneren" in out["text"]

    def test_select_enqueues_structure_task(self, db, shop):
        from django.utils import timezone

        _bp(
            shop,
            status=BlueprintStatus.IDEAS,
            product_ideas={"ideas": [], "avoid": []},
            started_products_at=timezone.now(),
        )
        with patch("apps.generator.start_views.generate_store_structure") as gen:
            _post(shop, {"action": "select_products", "product_gid": [G1, G2]})
        gen.delay.assert_called_once()


class TestStructureEdits:
    def _bp_with(self, shop: Shop) -> StoreBlueprint:
        return _bp(shop, store_structure=VALID_STRUCTURE)

    def test_rename_collection(self, db, shop):
        bp = self._bp_with(shop)
        _post(
            shop,
            {
                "action": "structure_rename",
                "item_type": "collection",
                "index": "0",
                "field": "title",
                "value": "Nieuwe Titel",
            },
        )
        bp.refresh_from_db()
        assert bp.store_structure["collections"][0]["title"] == "Nieuwe Titel"

    def test_move_menu_item(self, db, shop):
        bp = self._bp_with(shop)
        _post(
            shop,
            {"action": "structure_move", "item_type": "menu", "index": "2", "dir": "up"},
        )
        bp.refresh_from_db()
        assert bp.store_structure["menu"][1]["title"] == "Rituelen"

    def test_delete_menu_refused_below_minimum(self, db, shop):
        minimal = {**VALID_STRUCTURE, "menu": VALID_STRUCTURE["menu"][:3]}
        bp = _bp(shop, store_structure=minimal)
        out = _post(shop, {"action": "structure_delete", "item_type": "menu", "index": "0"})
        bp.refresh_from_db()
        assert len(bp.store_structure["menu"]) == 3  # unchanged
        assert "3" in out["text"]

    def test_add_collection(self, db, shop):
        bp = self._bp_with(shop)
        _post(
            shop,
            {
                "action": "structure_add_collection",
                "title": "Cadeaus",
                "description": "Sets voor cadeaus.",
                "product_gid": [G1],
            },
        )
        bp.refresh_from_db()
        assert len(bp.store_structure["collections"]) == 3
        assert bp.store_structure["collections"][2]["product_gids"] == [G1]

    def test_add_page(self, db, shop):
        minimal_pages = {**VALID_STRUCTURE, "pages": ["shipping", "returns"]}
        bp = _bp(shop, store_structure=minimal_pages)
        _post(shop, {"action": "structure_add_page", "page_type": "about"})
        bp.refresh_from_db()
        assert bp.store_structure["pages"] == ["shipping", "returns", "about"]


class TestStructureConfirm:
    def _confirm(self, shop: Shop) -> dict:
        return _post(shop, {"action": "structure_confirm"})

    def test_valid_confirms_to_building(self, db, shop):
        bp = _bp(shop, store_structure=VALID_STRUCTURE)
        out = self._confirm(shop)
        bp.refresh_from_db()
        assert out["status"] == 302
        assert bp.status == BlueprintStatus.BUILDING

    def test_missing_selected_product_blocked(self, db, shop):
        structure = {
            **VALID_STRUCTURE,
            "collections": [{"title": "Alleen een", "description": "d", "product_gids": [G1]}],
        }
        bp = _bp(shop, store_structure=structure)
        self._confirm(shop)
        bp.refresh_from_db()
        assert bp.status == BlueprintStatus.STRUCTURE

    def test_missing_required_pages_blocked(self, db, shop):
        structure = {**VALID_STRUCTURE, "pages": ["about", "faq"]}
        _bp(shop, store_structure=structure)
        out = self._confirm(shop)
        assert "shipping" in out["text"] or "returns" in out["text"]

    def test_unresolved_menu_ref_blocked(self, db, shop):
        structure = {
            **VALID_STRUCTURE,
            "menu": VALID_STRUCTURE["menu"][:2]
            + [{"title": "Bestaat niet", "target": "collection", "ref": "Ghost"}]
            + VALID_STRUCTURE["menu"][2:],
        }
        _bp(shop, store_structure=structure)
        out = self._confirm(shop)
        assert out["status"] == 200


class TestStructurePanelLegacyData:
    def test_int_webhook_gid_does_not_crash(self, db, shop):
        """Legacy webhook rows stored the product id as an int (pre T-114
        fix); the structure panel must normalize, not crash."""
        _bp(
            shop,
            store_structure=VALID_STRUCTURE,
            imported_products=[{"gid": 111, "title": "Legacy", "vendor": "CJ", "created_at": "2026-10-02T07:00:00Z"}],
            selected_product_gids=["gid://shopify/Product/111", G2],
        )
        token = _token(shop)
        resp = Client().get(f"/app/start/?id_token={token}")
        assert resp.status_code == 200
