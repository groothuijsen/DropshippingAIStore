"""Tests for T-085: legal templates + withdrawal labels + mq-withdrawal-link + checklist."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.compliance.legal import (
    DRAFT_BANNERS,
    WITHDRAWAL_TEMPLATES,
    fill_template,
    get_legal_pages,
    get_withdrawal_checklist,
)
from apps.compliance.withdrawal_labels import (
    get_all_labels,
    get_withdrawal_labels,
)
from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus

EXT_DIR = Path(__file__).resolve().parent.parent / "extensions" / "theme-blocks"
BLOCK = EXT_DIR / "blocks" / "mq-withdrawal-link.liquid"


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
        name="Test Winkel",
        email="info@test.nl",
    )


class TestWithdrawalLabels:
    def test_nl_labels(self):
        link, confirm = get_withdrawal_labels("nl")
        assert link == "Hier de overeenkomst ontbinden"
        assert confirm == "Ontbinding bevestigen"

    def test_de_labels(self):
        link, confirm = get_withdrawal_labels("de")
        assert link == "Vertrag widerrufen"
        assert confirm == "Widerruf bestätigen"

    def test_en_labels(self):
        link, confirm = get_withdrawal_labels("en")
        assert link == "Withdraw from contract here"
        assert confirm == "Confirm withdrawal"

    def test_fallback_to_en(self):
        link, confirm = get_withdrawal_labels("fr")
        assert link == "Withdraw from contract here"

    def test_all_labels(self):
        labels = get_all_labels()
        assert "nl" in labels
        assert "de" in labels
        assert "en" in labels
        assert labels["nl"]["link"] == "Hier de overeenkomst ontbinden"


class TestLegalTemplates:
    def test_templates_exist_for_all_langs(self):
        assert "nl" in WITHDRAWAL_TEMPLATES
        assert "de" in WITHDRAWAL_TEMPLATES
        assert "en" in WITHDRAWAL_TEMPLATES

    def test_draft_banner(self):
        assert "Concept" in DRAFT_BANNERS["nl"]
        assert "Draft" in DRAFT_BANNERS["en"]
        assert "Entwurf" in DRAFT_BANNERS["de"]

    def test_fill_template(self, shop):
        result = fill_template("Shop: [Shop name], Email: [Email]", shop)
        assert "Test Winkel" in result
        assert "info@test.nl" in result

    def test_fill_template_no_email(self, shop):
        shop.email = ""
        result = fill_template("Email: [Email]", shop)
        assert "[Email]" in result


class TestLegalPages:
    def test_withdrawal_page_nl(self, shop):
        pages = get_legal_pages(shop, "nl")
        withdrawal_pages = [p for p in pages if p["key"] == "withdrawal"]
        assert len(withdrawal_pages) == 1
        assert "Concept" in withdrawal_pages[0]["html_content"]
        assert "Herroepingsrecht" in withdrawal_pages[0]["html_content"]

    def test_impressum_de_only(self, shop):
        pages_de = get_legal_pages(shop, "de")
        impressum_de = [p for p in pages_de if p["key"] == "impressum"]
        assert len(impressum_de) == 1

        pages_nl = get_legal_pages(shop, "nl")
        impressum_nl = [p for p in pages_nl if p["key"] == "impressum"]
        assert len(impressum_nl) == 0

    def test_gpsr_contact_page(self, shop):
        pages = get_legal_pages(shop, "en")
        gpsr = [p for p in pages if p["key"] == "gpsr_contact"]
        assert len(gpsr) == 1

    def test_all_pages_are_draft(self, shop):
        pages = get_legal_pages(shop, "nl")
        for page in pages:
            assert page["is_draft"] is True

    def test_no_pages_for_unknown_locale(self, shop):
        pages = get_legal_pages(shop, "fr")
        assert len(pages) == 0


class TestWithdrawalChecklist:
    def test_checklist_nl(self):
        checklist = get_withdrawal_checklist("test-store.myshopify.com", "nl")
        assert len(checklist) == 4
        assert checklist[0]["label"] == "Zelfservice retouren ingeschakeld"

    def test_checklist_de(self):
        checklist = get_withdrawal_checklist("test-store.myshopify.com", "de")
        assert checklist[0]["label"] == "Self-Service-Rückgaben aktiviert"

    def test_checklist_deep_links(self):
        checklist = get_withdrawal_checklist("test-store.myshopify.com", "nl")
        for item in checklist:
            assert "admin.shopify.com/store/test-store" in item["deep_link"]

    def test_checklist_fallback_en(self):
        checklist = get_withdrawal_checklist("test-store.myshopify.com", "fr")
        assert checklist[0]["label"] == "Self-service returns enabled"


class TestWithdrawalLinkLiquid:
    def test_block_exists(self):
        assert BLOCK.exists()

    def test_block_reads_withdrawal_metafield(self):
        src = BLOCK.read_text()
        assert 'shop.metafields["$app:mosaiq"].withdrawal.value' in src

    def test_block_links_to_proxy(self):
        src = BLOCK.read_text()
        assert "/apps/mosaiq/withdraw" in src

    def test_block_places_in_footer(self):
        src = BLOCK.read_text()
        assert "footer" in src.lower()

    def test_block_fixed_fallback(self):
        src = BLOCK.read_text()
        assert "position: fixed" in src

    def test_locales_have_withdrawal_labels(self):
        for locale in ["en.default.json", "nl.json", "de.json"]:
            data = json.loads((EXT_DIR / "locales" / locale).read_text())
            wd = data.get("withdrawal", {})
            for key in ["link", "confirm"]:
                assert key in wd, f"{locale} missing withdrawal.{key}"
