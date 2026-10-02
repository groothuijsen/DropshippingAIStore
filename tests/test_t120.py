"""Tests for T-120: plain-language page edits (F16-2, 4, 5, 8; 12 §2.5, §3, §7).

The merchant types an instruction; one AI call returns operations; the code
validates (12 §3 rules), the merchant approves, apply bumps Page.version,
re-runs the claim check and counts towards `page_edits`.
"""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.ai.schemas import EditOp, PageEditResult
from apps.billing.models import Subscription
from apps.billing.plans import PLAN_LIMITS
from apps.core.models import Shop
from apps.generator.edit_ops import (
    EDIT_LOCKED_FIELDS,
    EditApplyError,
    apply_edit,
    validate_edit_ops,
)
from apps.generator.models import Page, PageStatus

PRODUCT_GID = "gid://shopify/Product/555"

PDP_SECTIONS = [
    {"type": "hero", "headline": "Snel scheren", "subheadline": "Elke ochtend", "cta_label": "Koop nu"},
    {"type": "benefits", "title": "Voordelen", "items": [{"title": "Snel", "text": "Direct klaar"}]},
    {
        "type": "faq",
        "items": [
            {"q": "Werkt het?", "a": "Ja, heel goed."},
            {"q": "Hoe snel?", "a": "Binnen twee werkdagen."},
            {"q": "Garantie?", "a": "Twee jaar fabrieksgarantie."},
            {"q": "Retourneren?", "a": "Binnen 14 dagen, gratis."},
        ],
    },
]

EDIT_LOCKED_SAMPLE = ["type", "image_slot", "price*", "offer*", "gpsr*", "unit_price*", "prior_price*"]


def _payload(sections=None):
    return {"locale": "nl", "page_type": "pdp", "seo_title": "T", "seo_description": "D", "sections": sections or [dict(s) for s in PDP_SECTIONS]}


@pytest.fixture()
def shop(db) -> Shop:
    return Shop.objects.create(
        domain="t120-test.myshopify.com",
        shopify_gid="gid://shopify/Shop/t120",
        access_token_encrypted=b"\x00" * 32,
        refresh_token_encrypted=b"\x00" * 32,
    )


@pytest.fixture()
def starter_subscription(db, shop) -> Subscription:
    return Subscription.objects.create(shop=shop, plan="starter", status="active")


@pytest.fixture()
def pdp_page(db, shop) -> Page:
    return Page.objects.create(
        shop=shop,
        page_type="pdp",
        title="Scheren",
        content_locale="nl",
        sections={"nl": _payload()},
        status=PageStatus.DRAFT,
        version=3,
        product_gid=PRODUCT_GID,
    )


# ── Schemas (12 §3) ────────────────────────────────────────────────────────


class TestSchemas:
    def test_edit_op_roundtrip(self):
        op = EditOp(op="replace_field", section_index=0, field="headline", value="Premium scheren")
        assert op.op == "replace_field"
        assert PageEditResult(operations=[op], summary="Hero aangepast.").summary == "Hero aangepast."

    def test_page_edit_result_bounds(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PageEditResult(operations=[], summary="x")
        ops = [EditOp(op="move_section", section_index=i, to_index=0) for i in range(11)]
        with pytest.raises(ValidationError):
            PageEditResult(operations=ops, summary="x")

    def test_locked_field_prefixes(self):
        assert "price" in EDIT_LOCKED_FIELDS
        assert "offer" in EDIT_LOCKED_FIELDS
        assert "gpsr" in EDIT_LOCKED_FIELDS
        assert "unit_price" in EDIT_LOCKED_FIELDS
        assert "prior_price" in EDIT_LOCKED_FIELDS
        assert "type" in EDIT_LOCKED_FIELDS
        assert "image_slot" in EDIT_LOCKED_FIELDS


# ── Validation engine (12 §3 rules) ────────────────────────────────────────


class TestValidation:
    def _validate(self, page_type, sections, ops):
        return validate_edit_ops(_payload(sections) if sections is not None else _payload(), page_type, ops)

    def test_valid_replace_field(self):
        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Premium scheren"}]
        assert self._validate("pdp", None, ops) == []

    def test_replace_dotted_path(self):
        ops = [{"op": "replace_field", "section_index": 2, "field": "items.0.q", "value": "Werkt het echt?"}]
        assert self._validate("pdp", None, ops) == []

    def test_replace_missing_path_rejected(self):
        ops = [{"op": "replace_field", "section_index": 0, "field": "nonexistent", "value": "x"}]
        assert self._validate("pdp", None, ops)

    def test_locked_price_rejected(self):
        ops = [{"op": "replace_field", "section_index": 0, "field": "price.amount", "value": "19.00"}]
        errors = self._validate("pdp", None, ops)
        assert errors and errors[0]["code"] == "EDIT_LOCKED_FIELDS"

    def test_locked_instruction_style_rejected(self):
        """F16-5: 'set the price to EUR 19' -> no such operation survives."""
        ops = [{"op": "replace_field", "section_index": 1, "field": "cta_label", "value": "Koop nu"},
               {"op": "replace_field", "section_index": 0, "field": "price", "value": "19"}]
        errors = self._validate("pdp", None, ops)
        assert any(e["code"] == "EDIT_LOCKED_FIELDS" for e in errors)

    def test_section_type_never_editable(self):
        ops = [{"op": "replace_field", "section_index": 0, "field": "type", "value": "faq"}]
        assert any(e["code"] == "EDIT_LOCKED_FIELDS" for e in self._validate("pdp", None, ops))

    def test_add_section_allowed_type(self):
        ops = [{"op": "add_section", "section_index": 3, "section": {"type": "guarantee", "text": "2 jaar garantie."}}]
        assert self._validate("pdp", None, ops) == []

    def test_add_unknown_section_type_rejected(self):
        ops = [{"op": "add_section", "section_index": 3, "section": {"type": "banner", "title": "X"}}]
        assert any(e["code"] == "EDIT_INVALID" for e in self._validate("pdp", None, ops))

    def test_remove_hero_on_pdp_rejected(self):
        ops = [{"op": "remove_section", "section_index": 0}]
        assert any(e["code"] == "EDIT_INVALID" for e in self._validate("pdp", None, ops))

    def test_minimum_two_sections_stays(self):
        ops = [{"op": "remove_section", "section_index": 1}, {"op": "remove_section", "section_index": 1}]
        assert any(e["code"] == "EDIT_INVALID" for e in self._validate("pdp", None, ops))

    def test_move_section(self):
        ops = [{"op": "move_section", "section_index": 2, "to_index": 1}]
        assert self._validate("pdp", None, ops) == []

    def test_faq_page_section_rules(self):
        """12 §3: faq pages allow rich_text + faq only."""
        sections = [
            {"type": "rich_text", "title": "Intro", "paragraphs": ["Welkom op onze pagina."]},
            {"type": "faq", "items": [{"q": "Q1?", "a": "A1."}, {"q": "Q2?", "a": "A2."}, {"q": "Q3?", "a": "A3."}, {"q": "Q4?", "a": "A4."}]},
        ]
        ok = [{"op": "replace_field", "section_index": 0, "field": "title", "value": "Veelgestelde vragen"}]
        assert self._validate("faq", sections, ok) == []
        ops = [{"op": "add_section", "section_index": 2, "section": {"type": "hero", "headline": "X", "subheadline": "Y", "cta_label": "Z"}}]
        assert any(e["code"] == "EDIT_INVALID" for e in self._validate("faq", sections, ops))

    def test_empty_operations_rejected(self):
        assert self._validate("pdp", None, [])


# ── Apply engine (F16-4) ───────────────────────────────────────────────────


class TestApply:
    def test_apply_bumps_version_and_rewrites_sections(self, pdp_page):
        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Premium scheren"}]
        apply_edit(pdp_page, "nl", ops, base_version=3)
        pdp_page.refresh_from_db()
        assert pdp_page.version == 4
        assert pdp_page.sections["nl"]["sections"][0]["headline"] == "Premium scheren"

    def test_apply_refused_on_version_mismatch(self, pdp_page):
        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "X"}]
        pdp_page.version = 9  # changed since the edit was proposed
        pdp_page.save(update_fields=["version"])
        with pytest.raises(EditApplyError, match="ask again"):
            apply_edit(pdp_page, "nl", ops, base_version=3)
        pdp_page.refresh_from_db()
        assert pdp_page.version == 9
        assert pdp_page.sections["nl"]["sections"][0]["headline"] == "Snel scheren"

    def test_apply_dotted_path(self, pdp_page):
        ops = [{"op": "replace_field", "section_index": 2, "field": "items.0.a", "value": "Ja, zeker."}]
        apply_edit(pdp_page, "nl", ops, base_version=3)
        pdp_page.refresh_from_db()
        assert pdp_page.sections["nl"]["sections"][2]["items"][0]["a"] == "Ja, zeker."

    def test_apply_recalculates_compliance(self, pdp_page):
        from apps.compliance.claims import check_sections

        ops = [{"op": "replace_field", "section_index": 2, "field": "items.0.a", "value": "Geneest hoofdpijn onmiddellijk."}]
        # Bypass the validator here — the apply-time claim check must still catch it
        apply_edit(pdp_page, "nl", ops, base_version=3)
        pdp_page.refresh_from_db()
        assert pdp_page.compliance_findings  # blocked/warn finding stored
        assert pdp_page.compliance_score < 100
        # The stored findings match a fresh deterministic check
        fresh = check_sections(pdp_page.sections["nl"]["sections"], "nl")
        assert len(fresh) == len(pdp_page.compliance_findings)

    def test_apply_add_and_remove(self, pdp_page):
        ops = [
            {"op": "add_section", "section_index": 3, "section": {"type": "guarantee", "text": "2 jaar."}},
            {"op": "remove_section", "section_index": 1},
        ]
        apply_edit(pdp_page, "nl", ops, base_version=3)
        pdp_page.refresh_from_db()
        types = [s["type"] for s in pdp_page.sections["nl"]["sections"]]
        assert "guarantee" in types
        assert "benefits" not in types

    def test_apply_move(self, pdp_page):
        ops = [{"op": "move_section", "section_index": 2, "to_index": 0}]
        apply_edit(pdp_page, "nl", ops, base_version=3)
        pdp_page.refresh_from_db()
        assert pdp_page.sections["nl"]["sections"][0]["type"] == "faq"

    def test_apply_on_live_page_changes_draft_only(self, pdp_page):
        """F16-6: live version stays until republish — apply touches local draft."""
        pdp_page.status = PageStatus.LIVE
        pdp_page.save(update_fields=["status"])
        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Nieuwe draft"}]
        apply_edit(pdp_page, "nl", ops, base_version=3)
        pdp_page.refresh_from_db()
        assert pdp_page.status == PageStatus.LIVE
        assert pdp_page.sections["nl"]["sections"][0]["headline"] == "Nieuwe draft"
        assert pdp_page.shopify_page_gid is None  # no publish side effects


# ── Limits (F16-8, 12 §7) ──────────────────────────────────────────────────


class TestLimits:
    def test_plan_limits_have_page_edits(self):
        assert PLAN_LIMITS["starter"]["page_edits"] == 50
        assert PLAN_LIMITS["pro"]["page_edits"] == 250
        assert PLAN_LIMITS["agency"]["page_edits"] == 1000

    def test_check_page_edits_under_limit(self, shop, starter_subscription):
        from apps.billing.limits import check_page_edits

        result = check_page_edits(shop)
        assert result.allowed is True

    def test_check_page_edits_over_limit(self, shop, starter_subscription):
        from apps.billing.limits import check_page_edits, get_current_period_start
        from apps.billing.models import UsageCounter

        UsageCounter.objects.create(shop=shop, period_start=get_current_period_start(), page_edits=50)
        result = check_page_edits(shop)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.reset_date is not None  # the UI shows the reset date

    def test_task_blocks_over_limit_before_ai_call(self, pdp_page, starter_subscription):
        from apps.billing.limits import get_current_period_start
        from apps.billing.models import UsageCounter
        from apps.generator.tasks import generate_page_edit

        UsageCounter.objects.create(
            shop=pdp_page.shop, period_start=get_current_period_start(), page_edits=50
        )
        with patch("apps.generator.tasks.call_ai") as mock_ai:
            edit = generate_page_edit(pdp_page.id, "nl", "Maak de hero premiumer")
        mock_ai.assert_not_called()
        edit.refresh_from_db()
        assert edit.status == "failed"
        assert edit.error_code == "PLAN_LIMIT_REACHED"


# ── Edit flow + PageEdit model (F16-2, 12 §2.5) ────────────────────────────


def _ai_result(operations, summary="Aangepast."):
    return PageEditResult.model_validate({"operations": operations, "summary": summary})


class TestEditFlow:
    def test_propose_creates_page_edit_and_calls_ai(self, pdp_page):
        from apps.generator.tasks import generate_page_edit

        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Premium scheren"}]
        with patch("apps.generator.tasks.call_ai", return_value=_ai_result(ops)) as mock_ai:
            edit = generate_page_edit(pdp_page.id, "nl", "Maak de hero premiumer")
        mock_ai.assert_called_once()
        assert edit.status == "proposed"
        assert edit.base_version == 3
        assert edit.operations == ops
        assert edit.summary
        assert edit.instruction == "Maak de hero premiumer"

    def test_invalid_instruction_fails_without_changes(self, pdp_page):
        from apps.generator.tasks import generate_page_edit

        ops = [{"op": "replace_field", "section_index": 0, "field": "price", "value": "19"}]
        with patch("apps.generator.tasks.call_ai", return_value=_ai_result(ops)):
            edit = generate_page_edit(pdp_page.id, "nl", "Zet de prijs op EUR 19")
        edit.refresh_from_db()
        assert edit.status == "failed"
        assert edit.error_code == "EDIT_INVALID"
        pdp_page.refresh_from_db()
        assert pdp_page.version == 3
        assert pdp_page.sections["nl"]["sections"][0]["headline"] == "Snel scheren"

    def test_invalid_edit_does_not_count(self, pdp_page, starter_subscription):
        """F16-2: EDIT_INVALID does not count towards page_edits."""
        from apps.billing.limits import get_current_period_start
        from apps.billing.models import UsageCounter
        from apps.generator.tasks import generate_page_edit

        counter = UsageCounter.objects.create(shop=pdp_page.shop, period_start=get_current_period_start())
        ops = [{"op": "remove_section", "section_index": 0}]  # hero on pdp -> EDIT_INVALID
        with patch("apps.generator.tasks.call_ai", return_value=_ai_result(ops)):
            generate_page_edit(pdp_page.id, "nl", "Verwijder de hero")
        counter.refresh_from_db()
        assert counter.page_edits == 0

    def test_apply_counts_page_edits(self, pdp_page, starter_subscription):
        from apps.billing.limits import get_current_period_start
        from apps.billing.models import UsageCounter
        from apps.generator.tasks import generate_page_edit

        UsageCounter.objects.create(shop=pdp_page.shop, period_start=get_current_period_start())
        ops = [{"op": "replace_field", "section_index": 0, "field": "headline", "value": "Premium scheren"}]
        with patch("apps.generator.tasks.call_ai", return_value=_ai_result(ops)):
            edit = generate_page_edit(pdp_page.id, "nl", "Premiumer")
        edit.status = "applied"
        edit.save(update_fields=["status"])
        from apps.billing.limits import consume

        consume(pdp_page.shop, "page_edits")
        counter = UsageCounter.objects.get(shop=pdp_page.shop)
        assert counter.page_edits == 1

    def test_instruction_max_500(self, pdp_page):
        from apps.generator.models import PageEdit

        edit = PageEdit(page=pdp_page, locale="nl", instruction="x" * 501, base_version=1)
        with pytest.raises(DjangoValidationError):
            edit.full_clean()

    def test_prompt_rendered_with_instruction(self, pdp_page):
        from apps.ai.prompts import render_prompt

        system, user = render_prompt(
            "edit_page",
            {
                "locale_name": "Dutch",
                "ui_locale_name": "Dutch",
                "page_type": "pdp",
                "sections_json": "[]",
                "scope": "whole page",
                "instruction": "Maak de hero premiumer",
                "tone": "confident",
                "facts_json": "[]",
                "allowed_sections_json": "[]",
                "locked_fields": ", ".join(EDIT_LOCKED_SAMPLE),
                "guardrails": "No medical claims.",
            },
        )
        assert "Maak de hero premiumer" in user
        assert "submit_page_edit" in system or "edit" in system.lower()
        assert "price" in system  # locked fields listed

    def test_scope_section_index_stored(self, pdp_page):
        from apps.generator.tasks import generate_page_edit

        ops = [{"op": "replace_field", "section_index": 2, "field": "items.0.q", "value": "Nieuwe vraag?"}]
        with patch("apps.generator.tasks.call_ai", return_value=_ai_result(ops)):
            edit = generate_page_edit(pdp_page.id, "nl", "Herschrijf de eerste veelgestelde vraag", scope_section_index=2)
        assert edit.scope_section_index == 2
        assert edit.status == "proposed"
