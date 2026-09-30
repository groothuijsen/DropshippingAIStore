"""Tests for T-073: cart drawer embed + cart config + cart upsell/reward schemas."""

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone
from pydantic import ValidationError

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.offers.cart_config import (
    MAX_UPSELL_PRODUCTS,
    build_cart_config,
    validate_cart_config,
)
from apps.offers.models import Offer, OfferStatus
from apps.offers.schemas import (
    CartUpsellRules,
    OfferConfig,
    RewardBarRules,
)

EXT_DIR = Path(__file__).resolve().parent.parent / "extensions" / "theme-blocks"
BLOCK = EXT_DIR / "blocks" / "mq-cart-drawer.liquid"


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


@pytest.fixture
def upsell_offer(shop):
    return Offer.objects.create(
        shop=shop,
        product_gid="gid://shopify/Product/1",
        title="Upsell Offer",
        kind="cart_upsell",
        config={
            "offer_id": "o1",
            "kind": "cart_upsell",
            "product_ids": ["gid://shopify/Product/1"],
            "cart_upsell": {"upsell_product_gids": ["gid://shopify/Product/2", "gid://shopify/Product/3"]},
            "labels": {"nl": "a", "en": "b", "de": "c"},
        },
        status=OfferStatus.ACTIVE,
    )


@pytest.fixture
def reward_offer(shop):
    return Offer.objects.create(
        shop=shop,
        product_gid="gid://shopify/Product/1",
        title="Reward Offer",
        kind="reward_bar",
        config={
            "offer_id": "o2",
            "kind": "reward_bar",
            "product_ids": ["gid://shopify/Product/1"],
            "reward_bar": {
                "thresholds": [
                    {
                        "amount": "50.00",
                        "label": {"nl": "Gratis verzending", "en": "Free shipping", "de": "Kostenloser Versand"},
                    },
                    {"amount": "75.00", "label": {"nl": "Cadeau", "en": "Gift", "de": "Geschenk"}},
                ],
                "shipping_rule_confirmed": True,
            },
            "labels": {"nl": "a", "en": "b", "de": "c"},
        },
        status=OfferStatus.ACTIVE,
    )


class TestCartUpsellRules:
    def test_valid(self):
        rules = CartUpsellRules(upsell_product_gids=["gid://shopify/Product/1", "gid://shopify/Product/2"])
        assert len(rules.upsell_product_gids) == 2

    def test_too_many(self):
        with pytest.raises(ValidationError):
            CartUpsellRules(upsell_product_gids=["1", "2", "3", "4"])

    def test_empty(self):
        with pytest.raises(ValidationError):
            CartUpsellRules(upsell_product_gids=[])


class TestRewardBarRules:
    def test_valid(self):
        rules = RewardBarRules(
            thresholds=[{"amount": "50.00", "label": {"nl": "a"}}],
            shipping_rule_confirmed=True,
        )
        assert rules.shipping_rule_confirmed is True

    def test_too_many_thresholds(self):
        thresholds = [{"amount": str(i), "label": {"nl": "x"}} for i in range(4)]
        with pytest.raises(ValidationError):
            RewardBarRules(thresholds=thresholds, shipping_rule_confirmed=True)

    def test_shipping_rule_confirmed_recorded(self):
        """shipping_rule_confirmed is a recorded boolean, not a gate."""
        rules = RewardBarRules(
            thresholds=[{"amount": "50.00"}],
            shipping_rule_confirmed=False,
        )
        assert rules.shipping_rule_confirmed is False


class TestOfferConfigCartKinds:
    def test_cart_upsell_valid(self):
        config = OfferConfig(
            offer_id="o1",
            kind="cart_upsell",
            product_ids=["x"],
            cart_upsell={"upsell_product_gids": ["y"]},
            labels={"nl": "a", "en": "b", "de": "c"},
        )
        assert config.kind == "cart_upsell"

    def test_cart_upsell_requires_block(self):
        with pytest.raises(ValidationError):
            OfferConfig(
                offer_id="o1",
                kind="cart_upsell",
                product_ids=["x"],
                labels={"nl": "a", "en": "b", "de": "c"},
            )

    def test_reward_bar_valid(self):
        config = OfferConfig(
            offer_id="o1",
            kind="reward_bar",
            product_ids=["x"],
            reward_bar={"thresholds": [{"amount": "50.00"}], "shipping_rule_confirmed": True},
            labels={"nl": "a", "en": "b", "de": "c"},
        )
        assert config.kind == "reward_bar"

    def test_volume_still_works(self):
        config = OfferConfig(
            offer_id="o1",
            kind="volume",
            product_ids=["x"],
            tiers=[{"min_qty": 2, "type": "percentage", "value": "10.0"}],
            labels={"nl": "a", "en": "b", "de": "c"},
        )
        assert config.kind == "volume"


class TestCartConfig:
    def test_build_cart_config(self, shop, upsell_offer, reward_offer):
        config = build_cart_config(shop)
        assert len(config["upsell_handles"]) == 2
        assert len(config["reward_thresholds"]) == 2
        assert "nl" in config["reward_labels"]

    def test_build_cart_config_no_offers(self, shop):
        config = build_cart_config(shop)
        assert config["upsell_handles"] == []
        assert config["reward_thresholds"] == []

    def test_build_cart_config_max_upsells(self, shop):
        Offer.objects.create(
            shop=shop,
            product_gid="x",
            title="T",
            kind="cart_upsell",
            config={
                "cart_upsell": {"upsell_product_gids": ["a", "b", "c", "d", "e"]},
                "labels": {"nl": "x", "en": "y", "de": "z"},
            },
            status=OfferStatus.ACTIVE,
        )
        config = build_cart_config(shop)
        assert len(config["upsell_handles"]) == MAX_UPSELL_PRODUCTS

    def test_validate_cart_config_valid(self):
        valid, msg = validate_cart_config({"upsell_handles": ["a"], "reward_thresholds": []})
        assert valid is True

    def test_validate_cart_config_too_many_upsells(self):
        valid, msg = validate_cart_config({"upsell_handles": ["a", "b", "c", "d"]})
        assert valid is False


class TestCartDrawerLiquid:
    def test_block_exists(self):
        assert BLOCK.exists()

    def _strip_comments(self, src: str) -> str:
        src = re.sub(r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", src, flags=re.DOTALL)
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        src = re.sub(r"^\s*//.*$", "", src, flags=re.MULTILINE)
        return src

    def test_block_uses_ajax_cart_api(self, block_src=None):
        src = BLOCK.read_text()
        code = self._strip_comments(src)
        assert "/cart.js" in code
        assert "/cart/add.js" in code
        assert "/cart/change.js" in code

    def test_block_reads_cart_metafield(self):
        src = BLOCK.read_text()
        assert 'shop.metafields["$app:mosaiq"].cart.value' in src

    def test_block_has_enabled_setting(self):
        src = BLOCK.read_text()
        assert '"enabled"' in src

    def test_block_intercepts_forms(self):
        src = BLOCK.read_text()
        assert "intercept" in src.lower()

    def test_block_has_upsells(self):
        src = BLOCK.read_text()
        assert "upsell" in src.lower()
        assert "all_products" in src

    def test_block_has_reward_bar(self):
        src = BLOCK.read_text()
        assert "reward" in src.lower()

    def test_locales_have_cart_drawer_keys(self):
        for locale in ["en.default.json", "nl.json", "de.json"]:
            data = json.loads((EXT_DIR / "locales" / locale).read_text())
            cd = data.get("cart_drawer", {})
            for key in ["title", "empty", "checkout", "subtotal"]:
                assert key in cd, f"{locale} missing cart_drawer.{key}"
