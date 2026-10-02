"""Tests for T-130: PricingSettings, VAT table, advise(), advisor screen (F17-1..3, 6..7)."""

from decimal import Decimal

import jwt as pyjwt
import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import Client

from apps.compliance.pricing_advisor import advise
from apps.compliance.vat_rates import VAT_STANDARD_RATES, vat_rate_for
from apps.core.models import Shop

BASE = {
    "cost": Decimal("8.00"),
    "shipping": Decimal("4.00"),
    "ad_cost": Decimal("0"),
    "payment_fee_fixed": Decimal("0.30"),
    "payment_fee_pct": Decimal("0.029"),
    "returns_pct": Decimal("0.05"),
    "margin_pct": Decimal("0.30"),
    "vat_rate": Decimal("0.21"),
    "price_ending": 95,
}


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t130-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t130-test",
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


class TestVatRates:
    def test_standard_rates_present(self):
        for country in ("NL", "BE", "DE", "AT", "FR", "LU", "IE"):
            assert country in VAT_STANDARD_RATES
            row = VAT_STANDARD_RATES[country]
            assert "rate" in row and "source" in row and "date" in row

    def test_gb_not_covered(self):
        assert vat_rate_for("GB") is None

    def test_nl_rate(self):
        assert vat_rate_for("NL") == Decimal("0.21")


class TestAdviseExactCases:
    """F17-1 test cases must pass exactly (price_ending=95)."""

    def test_case1_base(self):
        a = advise(**BASE)
        assert a.error is None
        assert a.net_price == Decimal("20.00")
        assert a.consumer_price == Decimal("24.20")
        assert a.rounded_price == Decimal("24.95")

    def test_case2_breakeven(self):
        a = advise(**{**BASE, "margin_pct": Decimal("0")})
        assert a.error is None
        assert a.break_even_price == Decimal("16.27")

    def test_case3_de_vat(self):
        a = advise(**{**BASE, "vat_rate": Decimal("0.19")})
        assert a.error is None
        assert a.consumer_price == Decimal("23.78")
        assert a.rounded_price == Decimal("23.95")

    def test_case4_ad_cost(self):
        a = advise(**{**BASE, "ad_cost": Decimal("5.00")})
        assert a.error is None
        assert a.consumer_price == Decimal("34.04")
        assert a.rounded_price == Decimal("34.95")

    def test_case5_margin_too_high(self):
        a = advise(**{**BASE, "returns_pct": Decimal("0.50"), "margin_pct": Decimal("0.42")})
        assert a.error is not None
        assert a.rounded_price is None

    def test_denominator_boundary_error(self):
        """r + m + p(1+v) >= 0.95 → error (denominator <= 0.05)."""
        a = advise(**{**BASE, "returns_pct": Decimal("0.45"), "margin_pct": Decimal("0.47")})
        assert a.error is not None

    def test_actual_margin_reported(self):
        a = advise(**BASE)
        assert a.actual_margin is not None
        assert a.actual_margin > Decimal("0.25")

    def test_price_ending_99(self):
        a = advise(**{**BASE, "price_ending": 99})
        assert a.rounded_price is not None
        assert str(a.rounded_price).endswith("99")
        assert a.rounded_price >= a.consumer_price

    def test_price_ending_00(self):
        a = advise(**{**BASE, "price_ending": 0})
        assert a.rounded_price is not None
        assert str(a.rounded_price).endswith("00")


class TestPricingSettings:
    def test_defaults(self, db, shop):
        from apps.compliance.models import PricingSettings

        p = PricingSettings.objects.create(shop=shop)
        p.full_clean()
        assert p.payment_fee_pct == Decimal("0.029")
        assert p.payment_fee_fixed == Decimal("0.30")
        assert p.returns_allowance_pct == Decimal("0.05")
        assert p.target_margin_pct == Decimal("0.30")
        assert p.price_ending == "95"
        assert p.markets == ["NL"]

    def test_validation_margin(self, db, shop):
        from apps.compliance.models import PricingSettings

        p = PricingSettings.objects.create(
            shop=shop, target_margin_pct=Decimal("0.90"), returns_allowance_pct=Decimal("0.10")
        )
        with pytest.raises(ValidationError):
            p.full_clean()


class TestAdvisorScreen:
    def _url(self, shop: Shop) -> str:
        return f"/app/products/gid%3A%2F%2Fshopify%2FProduct%2F9/pricing/?id_token={_token(shop)}"

    def test_get_renders_form(self, db, shop):
        resp = Client().get(self._url(shop))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "cost" in content
        assert "market" in content or "NL" in content

    def test_post_shows_advice(self, db, shop):
        resp = Client().post(
            self._url(shop),
            data={
                "cost": "8.00",
                "shipping": "4.00",
                "ad_cost": "0",
                "market": "NL",
            },
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "24.95" in content  # rounded advised price
        assert "24.20" in content  # consumer price

    def test_post_gb_not_covered(self, db, shop):
        resp = Client().post(
            self._url(shop),
            data={"cost": "8.00", "shipping": "4.00", "market": "GB"},
        )
        assert resp.status_code == 200
        assert "not covered" in resp.content.decode()

    def test_post_margin_error_shown(self, db, shop):
        resp = Client().post(
            self._url(shop),
            data={
                "cost": "8.00",
                "shipping": "4.00",
                "market": "NL",
                "margin_pct": "42",
                "returns_pct": "50",
            },
        )
        assert resp.status_code == 200
        assert "Target margin too high" in resp.content.decode()


class TestSettingsRedirect:
    def test_settings_index_redirects_keeping_qs(self, db, shop):
        token = _token(shop)
        resp = Client().get(f"/app/settings/?id_token={token}")
        assert resp.status_code == 302
        assert resp["Location"] == f"/app/settings/store/?id_token={token}"

    def test_settings_index_no_token_bounce(self, db, shop):
        # Without id_token the auth middleware shows the bounce page (200),
        # never the redirect — by design (docs 03 §2.1).
        resp = Client().get("/app/settings/")
        assert resp.status_code == 200
