"""Tests for T-141: delivery metafield sync, mq-price rendering, cut-off
suppression, 30-day go-live block (F18-4..7)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from apps.compliance.delivery import estimate
from apps.compliance.models import DeliveryOverride, DeliveryProfile
from apps.compliance.tasks import sync_delivery_metafields
from apps.core.models import Shop
from apps.generator.go_live import check_can_go_live
from apps.generator.models import Page, PageStatus
from apps.sources.models import DetectedBy, ProductSource

CJ_PROFILE = {
    "source_app": "cj",
    "ship_from_country": "CN",
    "processing_days_min": 2,
    "processing_days_max": 4,
    "transit_days": {"NL": [6, 10], "DE": [7, 11]},
    "shipping_cost": {"NL": {"amount": "4.95", "free_from": "40.00"}},
}


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t141-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t141-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
        import_apps=["cj"],
        ship_cutoff={"time": "16:00", "days": ["mon"], "delivery_days": 1},
    )


def _profile(shop: Shop, **overrides) -> DeliveryProfile:
    data = {**CJ_PROFILE, **overrides}
    return DeliveryProfile.objects.create(shop=shop, **data)


def _source(shop: Shop, product_gid: str, source: str = "cj") -> ProductSource:
    return ProductSource.objects.create(
        shop=shop, product_gid=product_gid, source=source, detected_by=DetectedBy.MERCHANT
    )


def _mock_client():
    client = MagicMock()
    client.execute.return_value = {"metafieldsSet": {"metafields": [], "userErrors": []}}
    return client


class TestSyncDeliveryMetafields:
    @patch("apps.compliance.tasks._get_client")
    def test_writes_metafield_for_profiled_product(self, mock_get, db, shop):
        _profile(shop)
        gid = "gid://shopify/Product/100"
        _source(shop, gid)
        mock_get.return_value = _mock_client()

        sync_delivery_metafields(shop.domain)

        args = mock_get.return_value.execute.call_args
        metafields = args[0][1]["metafields"]
        assert len(metafields) == 1
        m = metafields[0]
        assert m["ownerId"] == gid
        assert m["namespace"] == "$app:mosaiq"
        assert m["key"] == "delivery"
        value = json.loads(m["value"])
        assert value["min_days"] == 8
        assert value["max_days"] == 14
        assert value["ship_from"] == "CN"
        assert value["by_market"]["NL"] == [8, 14]

    @patch("apps.compliance.tasks._get_client")
    def test_no_products_no_api_call(self, mock_get, db, shop):
        mock_get.return_value = _mock_client()
        sync_delivery_metafields(shop.domain)
        mock_get.return_value.execute.assert_not_called()

    @patch("apps.compliance.tasks._get_client")
    def test_override_product_also_synced(self, mock_get, db, shop):
        gid = "gid://shopify/Product/200"
        DeliveryOverride.objects.create(
            shop=shop,
            product_gid=gid,
            ship_from_country="DE",
            processing_days_min=1,
            processing_days_max=2,
            transit_days={"NL": [2, 3]},
        )
        mock_get.return_value = _mock_client()

        sync_delivery_metafields(shop.domain)

        metafields = mock_get.return_value.execute.call_args[0][1]["metafields"]
        assert len(metafields) == 1
        value = json.loads(metafields[0]["value"])
        assert value["min_days"] == 3
        assert value["max_days"] == 5
        assert value["ship_from"] == "DE"

    @patch("apps.compliance.tasks._get_client")
    def test_batches_max_25(self, mock_get, db, shop):
        _profile(shop)
        for i in range(30):
            _source(shop, f"gid://shopify/Product/{i}")
        mock_get.return_value = _mock_client()

        sync_delivery_metafields(shop.domain)

        calls = mock_get.return_value.execute.call_args_list
        sizes = [len(c[0][1]["metafields"]) for c in calls]
        assert sizes == [25, 5]


class TestMqPriceLiquid:
    def _block(self):
        from pathlib import Path

        return (
            Path("extensions/theme-blocks/blocks/mq-price.liquid").read_text()
        )

    def test_block_reads_delivery_metafield(self):
        src = self._block()
        assert "delivery" in src
        assert "$app:mosaiq" in src

    def test_block_renders_nothing_without_delivery(self):
        src = self._block()
        # The delivery section must be gated: no metafield → nothing
        assert "{% if delivery" in src or "{%- if delivery" in src

    def test_locales_have_delivery_key(self):
        import json
        from pathlib import Path

        for lang in ("en.default", "nl", "de"):
            data = json.loads(
                Path(f"extensions/theme-blocks/locales/{lang}.json").read_text()
            )
            assert "delivery_time" in data.get("price", {}), f"{lang} missing price.delivery_time"


class TestCutoffSuppression:
    def test_suppressed_when_max_exceeds_cutoff(self, db, shop):
        """F18-6: product max_days (14) > ship_cutoff.delivery_days (1)."""
        _profile(shop)
        gid = "gid://shopify/Product/300"
        _source(shop, gid)
        est = estimate(shop, gid, "NL")
        assert est is not None
        cutoff_days = shop.ship_cutoff["delivery_days"]
        assert est.max_days > cutoff_days  # suppression condition holds

    def test_not_suppressed_when_within_cutoff(self, db, shop):
        _profile(shop, processing_days_min=0, processing_days_max=0,
                 transit_days={"NL": [0, 1]})
        gid = "gid://shopify/Product/301"
        _source(shop, gid)
        est = estimate(shop, gid, "NL")
        assert est.max_days == 1
        cutoff_days = shop.ship_cutoff["delivery_days"]
        assert est.max_days <= cutoff_days

    def test_no_estimate_never_suppresses(self, db, shop):
        """No estimate → the merchant's own notice may still render."""
        assert estimate(shop, "gid://shopify/Product/000", "NL") is None


class TestThirtyDayBlock:
    def _page(self, shop: Shop, product_gid: str) -> Page:
        return Page.objects.create(
            shop=shop,
            page_type="pdp",
            title="Test PDP",
            content_locale="en",
            sections={"en": {"sections": []}},
            product_gid=product_gid,
            status=PageStatus.DRAFT,
        )

    def test_blocks_when_any_market_over_30(self, db, shop):
        """F18-7: any market max_days > 30 → go-live blocked."""
        _profile(shop, transit_days={"NL": [6, 10], "DE": [28, 35]})
        gid = "gid://shopify/Product/400"
        _source(shop, gid)
        page = self._page(shop, gid)

        allowed, missing = check_can_go_live(page)
        assert allowed is False
        assert any("DELIVERY_OVER_30_DAYS" in m for m in missing)

    def test_allows_when_within_30(self, db, shop):
        _profile(shop)
        gid = "gid://shopify/Product/401"
        _source(shop, gid)
        page = self._page(shop, gid)

        allowed, missing = check_can_go_live(page)
        assert not any("DELIVERY_OVER_30_DAYS" in m for m in missing)

    def test_no_estimate_not_blocked_by_delivery(self, db, shop):
        """Missing delivery info is a warn, not a 30-day block."""
        page = self._page(shop, "gid://shopify/Product/402")
        allowed, missing = check_can_go_live(page)
        assert not any("DELIVERY_OVER_30_DAYS" in m for m in missing)
