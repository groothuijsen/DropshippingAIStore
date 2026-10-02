"""Tests for T-131: Apply price (F17-4..5) + guard tests + AuditLog.

Completes the F17 items deferred from T-130: current-price display (F17-3
remainder) and the Omnibus warning (F17-6).
"""

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client

from apps.compliance.models import PriceAdvice
from apps.core.models import AuditLog, Shop
from apps.sources.models import ProductSource
from apps.sources.rules import get_locked_fields

FIXTURES = Path(__file__).parent / "fixtures" / "shopify"

ADVICE_INPUTS = {
    "cost": "8.00",
    "shipping": "4.00",
    "market": "NL",
}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t131-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t131-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
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


def _advisor_url(shop: Shop, gid: str = "gid%3A%2F%2Fshopify%2FProduct%2F10781538812198") -> str:
    return f"/app/products/{gid}/pricing/?id_token={_token(shop)}"


def _apply_url(shop: Shop, gid: str = "gid%3A%2F%2Fshopify%2FProduct%2F10781538812198") -> str:
    return f"/app/products/{gid}/pricing/apply/?id_token={_token(shop)}"


def _product_gid() -> str:
    return "gid://shopify/Product/10781538812198"


def _mosaiq_source(shop: Shop, product_gid: str) -> ProductSource:
    return ProductSource.objects.create(
        shop=shop,
        product_gid=product_gid,
        source="manual",
        detected_by="mosaiq",
        created_by_mosaiq=True,
        locked_fields=[],
    )


def _sync_source(shop: Shop, product_gid: str, source: str = "cj") -> ProductSource:
    return ProductSource.objects.create(
        shop=shop,
        product_gid=product_gid,
        source=source,
        detected_by="import",
        created_by_mosaiq=False,
        locked_fields=get_locked_fields(source),
    )


def _mock_client():
    """Client mock returning fixture responses for the two reads + write."""
    client = MagicMock()
    variants = _fixture("product_variants_by_product")
    bulk = _fixture("product_variants_bulk_update")

    def _execute(query, variables=None):
        if "productVariantsBulkUpdate" in query:
            return bulk["response"]
        return variants["response"]

    client.execute.side_effect = _execute
    return client


class TestPriceAdviceModel:
    def test_row_created_on_calc(self, db, shop):
        resp = Client().post(_advisor_url(shop), data=ADVICE_INPUTS)
        assert resp.status_code == 200
        adv = PriceAdvice.objects.get(shop=shop, product_gid=_product_gid())
        assert adv.applied_at is None
        assert adv.advice["rounded"] == "24.95"
        assert adv.inputs["cost"] == "8.00"

    def test_gb_calc_no_row(self, db, shop):
        resp = Client().post(_advisor_url(shop), data={**ADVICE_INPUTS, "market": "GB"})
        assert resp.status_code == 200
        assert not PriceAdvice.objects.filter(shop=shop).exists()


class TestApplyWritable:
    def _calc_advice(self, shop) -> PriceAdvice:
        Client().post(_advisor_url(shop), data=ADVICE_INPUTS)
        return PriceAdvice.objects.get(shop=shop, product_gid=_product_gid())

    def test_apply_writes_price_and_audits(self, db, shop):
        _mosaiq_source(shop, _product_gid())
        advice = self._calc_advice(shop)
        client = _mock_client()
        with patch("apps.compliance.tasks._get_client", return_value=client):
            resp = Client().post(
                _apply_url(shop),
                data={"advice_id": str(advice.id)},
            )
        assert resp.status_code == 302
        advice.refresh_from_db()
        assert advice.applied_at is not None
        assert advice.applied_price == Decimal("24.95")
        # mutation called with price-only variants for all variant gids
        call_args = client.execute.call_args_list[-1]
        query, variables = call_args.args if call_args.args else (call_args.kwargs.get("query"), call_args.kwargs.get("variables"))
        assert "productVariantsBulkUpdate" in query
        assert variables["productId"] == _product_gid()
        assert variables["variants"] == [
            {"id": "gid://shopify/ProductVariant/53990753665318", "price": "24.95"}
        ]
        log = AuditLog.objects.get(shop=shop, action="price_advisor_applied")
        assert log.payload["price"] == "24.95"
        assert log.payload["product_gid"] == _product_gid()

    def test_apply_refused_without_source(self, db, shop):
        advice = self._calc_advice(shop)
        client = _mock_client()
        with patch("apps.compliance.tasks._get_client", return_value=client):
            resp = Client().post(_apply_url(shop), data={"advice_id": str(advice.id)})
        assert resp.status_code == 302
        advice.refresh_from_db()
        assert advice.applied_at is None
        client.execute.assert_not_called()
        assert not AuditLog.objects.filter(action="price_advisor_applied").exists()


class TestApplySyncApp:
    def test_screen_shows_copy_panel_no_apply(self, db, shop):
        gid = "gid://shopify/Product/555"
        _sync_source(shop, gid, "cj")
        url = _advisor_url(shop, gid.replace(":", "%3A").replace("/", "%2F"))
        client = _mock_client()
        with patch("apps.compliance.tasks._get_client", return_value=client):
            resp = Client().post(url, data=ADVICE_INPUTS)
        content = resp.content.decode()
        assert "Set this price in CJ Dropshipping (price rules)" in content
        assert 'name="advice_id"' not in content  # no Apply form

    def test_apply_guard_raises_no_http(self, db, shop):
        gid = "gid://shopify/Product/555"
        _sync_source(shop, gid, "cj")
        gid_url = gid.replace(":", "%3A").replace("/", "%2F")
        client = _mock_client()
        with patch("apps.compliance.tasks._get_client", return_value=client):
            Client().post(_advisor_url(shop, gid_url), data=ADVICE_INPUTS)
            advice = PriceAdvice.objects.get(shop=shop, product_gid=gid)
            resp = Client().post(_apply_url(shop, gid_url), data={"advice_id": str(advice.id)})
        advice.refresh_from_db()
        assert advice.applied_at is None
        # F17-5: no WRITE call — the only calls are the current-price read
        write_calls = [
            c for c in client.execute.call_args_list
            if "productVariantsBulkUpdate" in str(c)
        ]
        assert write_calls == []
        assert resp.status_code == 302


class TestApplyUserErrors:
    def test_user_error_blocks_apply(self, db, shop):
        from apps.core.shopify_client import ShopifyUserError

        _mosaiq_source(shop, _product_gid())
        Client().post(_advisor_url(shop), data=ADVICE_INPUTS)
        advice = PriceAdvice.objects.get(shop=shop, product_gid=_product_gid())
        client = MagicMock()
        client.execute.side_effect = ShopifyUserError(field="variants", message="Invalid price")
        with patch("apps.compliance.tasks._get_client", return_value=client):
            resp = Client().post(_apply_url(shop), data={"advice_id": str(advice.id)})
        advice.refresh_from_db()
        assert advice.applied_at is None
        assert resp.status_code == 302
        assert not AuditLog.objects.filter(action="price_advisor_applied").exists()


class TestOmnibusAndCurrentPrice:
    def test_current_price_and_omnibus_warning(self, db, shop):
        _mosaiq_source(shop, _product_gid())
        client = _mock_client()

        def _execute(query, variables=None):
            if "productVariantsBulkUpdate" in query:
                return _fixture("product_variants_bulk_update")["response"]
            resp = _fixture("product_variants_by_product")["response"]
            # current price 10.00 (below the advised 24.95 → Omnibus warning)
            resp["product"]["variants"]["nodes"][0]["price"] = "10.00"
            return resp

        client.execute.side_effect = _execute
        with patch("apps.compliance.tasks._get_client", return_value=client):
            resp = Client().post(_advisor_url(shop), data=ADVICE_INPUTS)
        content = resp.content.decode()
        assert "10.00" in content  # current price shown
        assert "lowest price of the 30 days before the discount" in content  # Omnibus (F17-6)

    def test_no_warning_when_advised_below_current(self, db, shop):
        _mosaiq_source(shop, _product_gid())
        client = _mock_client()

        def _execute(query, variables=None):
            if "productVariantsBulkUpdate" in query:
                return _fixture("product_variants_bulk_update")["response"]
            resp = _fixture("product_variants_by_product")["response"]
            resp["product"]["variants"]["nodes"][0]["price"] = "99.00"
            return resp

        client.execute.side_effect = _execute
        with patch("apps.compliance.tasks._get_client", return_value=client):
            resp = Client().post(_advisor_url(shop), data=ADVICE_INPUTS)
        content = resp.content.decode()
        assert "lowest price of the 30 days before the discount" not in content
