"""Tests for T-142: SHIPPING_CLAIM rule + copy-step delivery input (F18-8..9)."""

import json
from pathlib import Path

from apps.compliance.claims import (
    check_claims,
    check_sections,
    validate_rule_id,
)
from apps.compliance.delivery import DeliveryEstimate
from apps.generator.copy_step import delivery_guardrail

FAST_NL = "Geniet van snelle levering van dit product."
FAST_EN = "Order now for fast shipping today."
FAST_DE = "Bestellen Sie jetzt für schnelle Lieferung."
EU_NL = "Verzonden vanuit ons EU-magazijn."
NO_CLAIM_NL = "Dit kussen ondersteunt een goede nachtrust."


class TestShippingClaimRule:
    def test_rule_id_valid(self):
        assert validate_rule_id("SHIPPING_CLAIM")

    def test_fast_claim_block_when_max_over_3(self):
        """F18-8: 'snelle levering' with NL estimate 8-14 → block."""
        for text, locale in ((FAST_NL, "nl"), (FAST_EN, "en"), (FAST_DE, "de")):
            findings = check_claims(
                text,
                locale,
                delivery={"max_days": 14, "ship_from": "CN"},
            )
            assert len(findings) == 1, f"{locale}: expected 1 finding"
            assert findings[0].rule_id == "SHIPPING_CLAIM"
            assert findings[0].is_block

    def test_fast_claim_no_finding_when_max_3_or_less(self):
        """Fast claim with estimate 1-2 → no finding (claim is truthful)."""
        findings = check_claims(
            FAST_NL, "nl", delivery={"max_days": 2, "ship_from": "DE"}
        )
        assert findings == []

    def test_fast_claim_warn_when_no_estimate(self):
        """No estimate → warn, not block (merchant may ship fast)."""
        findings = check_claims(FAST_NL, "nl", delivery=None)
        assert len(findings) == 1
        assert findings[0].is_warn
        assert findings[0].rule_id == "SHIPPING_CLAIM"

    def test_no_delivery_context_defaults_to_warn(self):
        findings = check_claims(FAST_NL, "nl")
        assert len(findings) == 1
        assert findings[0].is_warn

    def test_eu_ship_claim_blocked_from_cn(self):
        findings = check_claims(
            EU_NL, "nl", delivery={"max_days": 14, "ship_from": "CN"}
        )
        assert len(findings) == 1
        assert findings[0].is_block

    def test_eu_ship_claim_allowed_from_eu(self):
        findings = check_claims(
            EU_NL, "nl", delivery={"max_days": 8, "ship_from": "DE"}
        )
        assert findings == []

    def test_no_claim_no_finding(self):
        findings = check_claims(
            NO_CLAIM_NL, "nl", delivery={"max_days": 14, "ship_from": "CN"}
        )
        assert findings == []

    def test_existing_rules_still_work(self):
        findings = check_claims("Dit product is klinisch bewezen.", "nl")
        assert any(f.rule_id == "MED_CLAIM" and f.is_block for f in findings)

    def test_check_sections_passes_delivery(self):
        sections = [
            {"type": "hero", "heading": "Slaap beter", "body": FAST_NL},
        ]
        findings = check_sections(
            sections, "nl", delivery={"max_days": 14, "ship_from": "CN"}
        )
        assert any(f.rule_id == "SHIPPING_CLAIM" and f.is_block for f in findings)


class TestCopyStepGuardrail:
    def test_guardrail_with_estimate(self):
        """F18-9: guardrail names the actual max_days."""
        text = delivery_guardrail(DeliveryEstimate(
            min_days=8, max_days=14, ship_from="CN", source="profile"
        ))
        assert "14" in text
        assert "fast shipping" in text

    def test_guardrail_without_estimate(self):
        text = delivery_guardrail(None)
        assert text == ""


class TestEvalsetLongDelivery:
    def test_five_long_delivery_cases(self):
        """10 §4 / F18-9: 5 evalset cases with long delivery times."""
        data = json.loads(Path("tests/evalset/eval_products.json").read_text())
        long_cases = [
            p for p in data
            if (p.get("delivery_estimate") or {}).get("max_days", 0) > 10
        ]
        assert len(long_cases) >= 5
        for case in long_cases:
            assert case["delivery_estimate"]["max_days"] > 10
            assert case["delivery_estimate"]["ship_from"]
