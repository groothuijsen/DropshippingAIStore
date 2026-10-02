"""Tests for T-111: BusinessDetails model, is_complete, legal template filling."""

import django.core.exceptions
import jwt as pyjwt
import pytest
from django.conf import settings

from apps.compliance.legal import fill_legal_details
from apps.core.models import AuditLog, BusinessDetails, Shop

VALID = {
    "legal_name": "Mosaiq B.V.",
    "trade_name": "",
    "street": "Hoofdstraat 1",
    "postal_code": "1234AB",
    "city": "Amsterdam",
    "country_code": "NL",
    "email": "info@mosaiq.example",
    "phone": "+31 6 12345678",
    "company_reg_no": "86123456",
    "vat_id": "NL861234567B01",
}


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t111-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t111-test",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
    )


def _details(shop: Shop, **overrides) -> BusinessDetails:
    data = {**VALID, **overrides}
    return BusinessDetails.objects.create(shop=shop, **data)


def _session_token(shop: Shop) -> str:
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


class TestBusinessDetailsModel:
    def test_full_details_no_missing_for_legal(self, db, shop):
        _details(shop)
        assert BusinessDetails.objects.get(shop=shop).is_complete("legal") == []

    def test_is_complete_legal_returns_field_names(self, db, shop):
        d = _details(shop, legal_name="", street="", email="")
        missing = d.is_complete("legal")
        assert "legal_name" in missing
        assert "street" in missing
        assert "email" in missing
        assert "city" not in missing

    def test_is_complete_impressum_requires_company_reg_no(self, db, shop):
        d = _details(shop, company_reg_no="")
        missing = d.is_complete("impressum")
        assert "company_reg_no" in missing

    def test_is_complete_returns_uses_return_address_json(self, db, shop):
        d = _details(shop, return_address_same=False, return_address={})
        assert "return_address" in d.is_complete("returns")

    def test_is_complete_returns_satisfied_when_same(self, db, shop):
        _details(shop)
        assert BusinessDetails.objects.get(shop=shop).is_complete("returns") == []

    def test_one_per_shop(self, db, shop):
        _details(shop)
        with pytest.raises(django.db.IntegrityError):
            BusinessDetails.objects.create(shop=shop, **VALID)


class TestVatIdPrefixCheck:
    def test_valid_prefix_passes_clean(self, db, shop):
        d = _details(shop, country_code="NL", vat_id="NL861234567B01")
        d.full_clean()

    def test_prefix_mismatch_rejected(self, db, shop):
        d = _details(shop, country_code="NL", vat_id="DE123456789")
        with pytest.raises(django.core.exceptions.ValidationError):
            d.full_clean()


class TestFillLegalDetails:
    def test_placeholders_filled_when_details_complete(self, db, shop):
        d = _details(shop)
        result = fill_legal_details(
            "Aan: [Winkelnaam], [Adres], [E-mail] — [Straße und Hausnummer] "
            "[PLZ und Ort] [Land] [Winkelname]",
            d,
        )
        for placeholder in (
            "[Adres]",
            "[E-mail]",
            "[Straße und Hausnummer]",
            "[PLZ und Ort]",
            "[Land]",
            "[Winkelname]",
        ):
            assert placeholder not in result
        assert "Hoofdstraat 1" in result
        assert "1234AB Amsterdam" in result

    def test_placeholders_left_when_incomplete(self, db, shop):
        d = _details(shop, street="")
        result = fill_legal_details("Aan: [Adres]", d)
        # Incomplete — placeholder stays visible as draft marker
        assert "[Adres]" in result


class TestBusinessDetailsView:
    def test_get_renders_form(self, db, shop):
        from django.test import Client

        client = Client()
        resp = client.get(f"/app/settings/business/?id_token={_session_token(shop)}")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "legal_name" in content
        assert "postal_code" in content

    def test_post_saves_details(self, db, shop):
        from django.test import Client

        client = Client()
        resp = client.post(
            f"/app/settings/business/?id_token={_session_token(shop)}", data=VALID
        )
        assert resp.status_code == 302
        d = BusinessDetails.objects.get(shop=shop)
        assert d.legal_name == "Mosaiq B.V."
        assert d.postal_code == "1234AB"
        # AuditLog entry written (02: sensitive actions)
        assert AuditLog.objects.filter(shop=shop, action="business_details_saved").exists()
