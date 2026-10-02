"""Tests for T-121: editor UI for plain-language page edits (F16-1, 3, 4, 6, 7, 9)."""

from unittest.mock import patch

import pytest
from django.test import Client

from apps.ai.schemas import PageEditResult
from apps.core.models import Shop
from apps.generator.models import Page, PageEdit, PageStatus
from apps.generator.tasks import generate_page_edit

PRODUCT_GID = "gid://shopify/Product/777"

SECTIONS = [
    {"type": "hero", "headline": "Snel scheren", "subheadline": "Elke ochtend", "cta_label": "Koop nu"},
    {"type": "benefits", "title": "Voordelen", "items": [{"title": "Snel", "text": "Direct klaar"}]},
    {"type": "faq", "items": [
        {"q": "Werkt het?", "a": "Ja."},
        {"q": "Hoe snel?", "a": "Twee dagen."},
        {"q": "Garantie?", "a": "Twee jaar."},
        {"q": "Retour?", "a": "14 dagen."},
    ]},
]


def _payload():
    return {"locale": "nl", "page_type": "pdp", "seo_title": "T", "seo_description": "D", "sections": [dict(s) for s in SECTIONS]}


def _ai(operations, summary="Aangepast."):
    return PageEditResult.model_validate({"operations": operations, "summary": summary})


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t121-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t121",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
    )


@pytest.fixture()
def page(db, shop) -> Page:
    return Page.objects.create(
        shop=shop,
        page_type="pdp",
        title="Scheren",
        content_locale="nl",
        sections={"nl": _payload(), "en": _payload()},
        status=PageStatus.DRAFT,
        version=2,
        product_gid=PRODUCT_GID,
    )


def _auth(shop: Shop) -> str:
    import jwt as pyjwt
    from django.conf import settings

    return pyjwt.encode(
        {"iss": f"https://{shop.domain}/admin", "dest": f"https://{shop.domain}",
         "aud": settings.SHOPIFY_API_KEY, "sub": "1", "exp": 9999999999, "nbf": 1},
        settings.SHOPIFY_API_SECRET, algorithm="HS256",
    )


def _client_for_task():
    """Run the real generate_page_edit synchronously in place of .delay()."""
    return patch("apps.generator.editor_views.generate_page_edit.delay",
                 side_effect=lambda *a, **k: generate_page_edit(*a, **k))


class TestEditorScreen:
    def test_get_renders_instruction_and_sections(self, page, shop):
        token = _auth(shop)
        resp = Client().get(f"/app/pages/{page.id}/edit/?id_token={token}")
        assert resp.status_code == 200
        text = resp.content.decode()
        assert "Ask for a change" in text
        assert 'maxlength="500"' in text
        assert "Snel scheren" in text  # current sections visible
        assert "Apply to other languages" in text

    def test_per_section_buttons(self, page, shop):
        token = _auth(shop)
        resp = Client().get(f"/app/pages/{page.id}/edit/?id_token={token}")
        text = resp.content.decode()
        assert text.count("Ask for a change") >= 3  # one per section

    def test_live_page_shows_draft_note(self, page, shop):
        page.status = PageStatus.LIVE
        page.save(update_fields=["status"])
        token = _auth(shop)
        resp = Client().get(f"/app/pages/{page.id}/edit/?id_token={token}")
        assert "re-publish" in resp.content.decode()


class TestProposeAndDiff:
    def test_post_instruction_creates_proposed_edit_with_diff(self, page, shop):
        token = _auth(shop)
        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Premium scheren"}]
        with _client_for_task(), patch("apps.generator.tasks.call_ai", return_value=_ai(ops)):
            resp = Client().post(
                f"/app/pages/{page.id}/edit/?id_token={token}",
                data={"instruction": "Maak de hero premiumer", "locale": "nl"},
            )
            assert resp.status_code == 302
            resp = Client().get(f"/app/pages/{page.id}/edit/?id_token={token}")
        text = resp.content.decode()
        edit = PageEdit.objects.get(page=page)
        assert edit.status == "proposed"
        assert "Snel scheren" in text  # before value in the diff
        assert "Premium scheren" in text  # after value
        assert edit.summary in text

    def test_scope_section_button_posts_scope(self, page, shop):
        token = _auth(shop)
        ops = [{"op": "replace_field", "section_index": 2, "field": "items.0.q", "value": "Werkt het echt?"}]
        with _client_for_task(), patch("apps.generator.tasks.call_ai", return_value=_ai(ops)):
            Client().post(
                f"/app/pages/{page.id}/edit/?id_token={token}",
                data={"instruction": "Herschrijf de eerste veelgestelde vraag", "locale": "nl", "scope": "2"},
            )
        edit = PageEdit.objects.get(page=page)
        assert edit.scope_section_index == 2

    def test_apply_to_other_languages_queues_edits(self, page, shop):
        token = _auth(shop)
        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Premium scheren"}]
        with _client_for_task(), patch("apps.generator.tasks.call_ai", return_value=_ai(ops)):
            Client().post(
                f"/app/pages/{page.id}/edit/?id_token={token}",
                data={"instruction": "Premiumer", "locale": "nl", "other_locales": "on"},
            )
        locales = set(PageEdit.objects.filter(page=page).values_list("locale", flat=True))
        assert locales == {"nl", "en"}  # F16-7: one edit per locale, each counted

    def test_claim_finding_highlighted_but_apply_allowed(self, page, shop):
        token = _auth(shop)
        ops = [{"op": "replace_field", "section_index": 2, "field": "items.0.a", "value": "Geneest hoofdpijn onmiddellijk."}]
        with _client_for_task(), patch("apps.generator.tasks.call_ai", return_value=_ai(ops)):
            Client().post(
                f"/app/pages/{page.id}/edit/?id_token={token}",
                data={"instruction": "Maak de FAQ overtuigender", "locale": "nl"},
            )
        text = Client().get(f"/app/pages/{page.id}/edit/?id_token={token}").content.decode()
        assert "claim" in text.lower() or "compliance" in text.lower()  # highlighted
        assert text.count("Apply") >= 1  # F16-9: apply stays possible


class TestApplyReject:
    def _propose(self, page, shop, ops=None):
        ops = ops or [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Premium scheren"}]
        with _client_for_task(), patch("apps.generator.tasks.call_ai", return_value=_ai(ops)):
            Client().post(
                f"/app/pages/{page.id}/edit/?id_token={_auth(shop)}",
                data={"instruction": "Premiumer", "locale": "nl"},
            )
        return PageEdit.objects.get(page=page)

    def test_apply_updates_page_and_counts(self, page, shop):
        edit = self._propose(page, shop)
        token = _auth(shop)
        resp = Client().post(
            f"/app/pages/{page.id}/edit/{edit.id}/apply/?id_token={token}", data={}
        )
        assert resp.status_code == 302
        page.refresh_from_db()
        edit.refresh_from_db()
        assert edit.status == "applied"
        assert page.version == 3
        assert page.sections["nl"]["sections"][0]["headline"] == "Premium scheren"
        from apps.billing.models import UsageCounter

        counter = UsageCounter.objects.get(shop=shop)
        assert counter.page_edits == 1

    def test_apply_refused_when_page_changed(self, page, shop):
        edit = self._propose(page, shop)
        page.version += 1
        page.save(update_fields=["version"])
        token = _auth(shop)
        with patch("apps.generator.editor_views.messages") as mock_messages:
            Client().post(f"/app/pages/{page.id}/edit/{edit.id}/apply/?id_token={token}", data={})
            shown = " ".join(str(c) for c in mock_messages.method_calls)
        assert "ask again" in shown
        edit.refresh_from_db()
        assert edit.status == "proposed"  # stays proposed for a retry

    def test_reject_marks_rejected_without_changes(self, page, shop):
        edit = self._propose(page, shop)
        token = _auth(shop)
        Client().post(f"/app/pages/{page.id}/edit/{edit.id}/reject/?id_token={token}", data={})
        edit.refresh_from_db()
        page.refresh_from_db()
        assert edit.status == "rejected"
        assert page.version == 2
        assert page.sections["nl"]["sections"][0]["headline"] == "Snel scheren"

    def test_apply_counts_only_applied(self, page, shop):
        edit = self._propose(page, shop)
        token = _auth(shop)
        Client().post(f"/app/pages/{page.id}/edit/{edit.id}/reject/?id_token={token}", data={})
        from apps.billing.limits import get_current_period_start
        from apps.billing.models import UsageCounter

        counter, _ = UsageCounter.objects.get_or_create(shop=shop, period_start=get_current_period_start())
        assert counter.page_edits == 0  # rejected does not count


class TestLimit:
    def test_over_limit_disables_field_with_reset_date(self, page, shop):
        from apps.billing.limits import get_current_period_start
        from apps.billing.models import UsageCounter
        from apps.billing.plans import PLAN_LIMITS

        UsageCounter.objects.create(
            shop=shop, period_start=get_current_period_start(), page_edits=PLAN_LIMITS["starter"]["page_edits"]
        )
        token = _auth(shop)
        resp = Client().get(f"/app/pages/{page.id}/edit/?id_token={token}")
        text = resp.content.decode()
        assert "disabled" in text
        assert "resets" in text  # reset date shown (F16-8)

    def test_post_refused_over_limit(self, page, shop):
        from apps.billing.limits import get_current_period_start
        from apps.billing.models import UsageCounter
        from apps.billing.plans import PLAN_LIMITS

        UsageCounter.objects.create(
            shop=shop, period_start=get_current_period_start(), page_edits=PLAN_LIMITS["starter"]["page_edits"]
        )
        token = _auth(shop)
        with _client_for_task(), patch("apps.generator.tasks.call_ai") as mock_ai:
            Client().post(
                f"/app/pages/{page.id}/edit/?id_token={token}",
                data={"instruction": "Premiumer", "locale": "nl"},
            )
        mock_ai.assert_not_called()
        assert PageEdit.objects.filter(page=page).count() == 0
