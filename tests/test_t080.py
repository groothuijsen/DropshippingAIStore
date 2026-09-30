"""Tests for T-080: claims blocklist + AI check + ClaimFinding + score."""

from apps.compliance.claims import (
    BLOCKLIST,
    VALID_RULE_IDS,
    Finding,
    check_claims,
    check_sections,
    validate_rule_id,
)
from apps.compliance.scoring import claims_score, has_open_block, page_score

# ── Blocklist tests ───────────────────────────────────────────────────────


class TestBlocklist:
    def test_all_rules_have_patterns(self):
        for rule_id, rule in BLOCKLIST.items():
            assert "patterns" in rule, f"{rule_id} missing patterns"
            assert "severity" in rule, f"{rule_id} missing severity"
            assert rule["severity"] in ("block", "warn")

    def test_all_languages_covered(self):
        for rule_id, rule in BLOCKLIST.items():
            patterns = rule.get("patterns", {})
            for lang in ["nl", "en", "de"]:
                assert lang in patterns, f"{rule_id} missing {lang} patterns"

    def test_valid_rule_ids(self):
        assert "EMPCO_GENERIC" in VALID_RULE_IDS
        assert "MED_CLAIM" in VALID_RULE_IDS
        assert "EMPCO_LABEL" in VALID_RULE_IDS
        assert "UNSUPPORTED_FACT" in VALID_RULE_IDS
        assert "IP_REFERENCE" in VALID_RULE_IDS


# ── Deterministic check tests ─────────────────────────────────────────────


class TestCheckClaims:
    def test_emco_generic_nl(self):
        findings = check_claims("Dit is een duurzaam product", "nl")
        assert len(findings) == 1
        assert findings[0].rule_id == "EMPCO_GENERIC"
        assert findings[0].is_block

    def test_med_claim_nl(self):
        findings = check_claims("Dit geneest slapeloosheid", "nl")
        assert len(findings) == 1
        assert findings[0].rule_id == "MED_CLAIM"

    def test_fake_urgency_nl(self):
        findings = check_claims("Alleen vandaag! Op=op!", "nl")
        assert len(findings) == 1
        assert findings[0].rule_id == "FAKE_URGENCY"

    def test_superlative_warn(self):
        findings = check_claims("Dit is de beste optie", "nl")
        assert len(findings) == 1
        assert findings[0].rule_id == "SUPERLATIVE"
        assert findings[0].is_warn

    def test_case_insensitive(self):
        findings = check_claims("DUURZAAM product", "nl")
        assert len(findings) == 1

    def test_word_boundary(self):
        # "duurzaamheid" should not match "duurzaam" (\b boundary)
        result = check_claims("Dit gaat over duurzaamheid als concept", "nl")
        # Should not match because \b prevents partial word matches
        assert all(f.rule_id != "EMPCO_GENERIC" for f in result)

    def test_no_claims_clean_text(self):
        findings = check_claims("Een mooi product van hoge kwaliteit", "nl")
        assert len(findings) == 0

    def test_emco_en(self):
        findings = check_claims("This is a sustainable product", "en")
        assert len(findings) == 1
        assert findings[0].rule_id == "EMPCO_GENERIC"

    def test_med_claim_en(self):
        findings = check_claims("This cures insomnia", "en")
        assert len(findings) == 1
        assert findings[0].rule_id == "MED_CLAIM"

    def test_auto_roadlegal_nl(self):
        findings = check_claims("Dit product is straatlegaal", "nl", niche="auto_accessories")
        assert len(findings) == 1
        assert findings[0].rule_id == "AUTO_ROADLEGAL"

    def test_auto_roadlegal_wrong_niche(self):
        findings = check_claims("Dit product is straatlegaal", "nl", niche="wellness_sleep")
        assert len(findings) == 0

    def test_emco_generic_fact_exception(self):
        """EMPCO_GENERIC becomes warn if sentence contains specific fact."""
        findings = check_claims(
            "Duurzaam product van 100% gerecycled polyester",
            "nl",
            facts=["100% gerecycled polyester"],
        )
        assert len(findings) == 1
        assert findings[0].rule_id == "EMPCO_GENERIC"
        assert findings[0].is_warn  # Downgraded due to specific fact

    def test_empty_text(self):
        findings = check_claims("", "nl")
        assert findings == []


# ── Section check tests ───────────────────────────────────────────────────


class TestCheckSections:
    def test_checks_all_sections(self):
        sections = [
            {"type": "hero", "headline": "Duurzaam product", "subheadline": "Snel resultaat"},
            {"type": "cta", "headline": "Koop nu", "subheadline": "Alleen vandaag"},
        ]
        findings = check_sections(sections, "nl")
        # Should find EMPCO_GENERIC in hero + FAKE_URGENCY in cta
        rule_ids = [f.rule_id for f in findings]
        assert "EMPCO_GENERIC" in rule_ids
        assert "FAKE_URGENCY" in rule_ids

    def test_checks_nested_items(self):
        sections = [
            {
                "type": "faq",
                "items": [
                    {"question": "Wat is dit?", "answer": "Een duurzaam product"},
                ],
            },
        ]
        findings = check_sections(sections, "nl")
        assert any(f.rule_id == "EMPCO_GENERIC" for f in findings)

    def test_clean_sections_no_findings(self):
        sections = [
            {"type": "hero", "headline": "Mooi product", "subheadline": "Van hoge kwaliteit"},
        ]
        findings = check_sections(sections, "nl")
        assert findings == []


# ── Rule ID validation tests ──────────────────────────────────────────────


class TestRuleIdValidation:
    def test_valid_rule_ids(self):
        assert validate_rule_id("EMPCO_GENERIC") is True
        assert validate_rule_id("MED_CLAIM") is True
        assert validate_rule_id("EMPCO_LABEL") is True

    def test_invalid_rule_ids(self):
        assert validate_rule_id("FAKE_RULE") is False
        assert validate_rule_id("") is False


# ── Scoring tests ─────────────────────────────────────────────────────────


class TestScoring:
    def test_no_findings_score_100(self):
        assert claims_score([]) == 100

    def test_one_block_costs_25(self):
        findings = [Finding(rule_id="MED_CLAIM", severity="block", text="test")]
        assert claims_score(findings) == 75

    def test_one_warn_costs_5(self):
        findings = [Finding(rule_id="SUPERLATIVE", severity="warn", text="test")]
        assert claims_score(findings) == 95

    def test_mixed_findings(self):
        findings = [
            Finding(rule_id="MED_CLAIM", severity="block", text="t"),
            Finding(rule_id="SUPERLATIVE", severity="warn", text="t"),
        ]
        assert claims_score(findings) == 70

    def test_override_excluded(self):
        findings = [
            Finding(rule_id="MED_CLAIM", severity="block", text="t", override_reason="Verified"),
        ]
        assert claims_score(findings) == 100

    def test_minimum_zero(self):
        findings = [Finding(rule_id="X", severity="block", text="t") for _ in range(5)]
        assert claims_score(findings) == 0


# ── Page score tests ──────────────────────────────────────────────────────


class TestPageScore:
    def test_perfect_page(self):
        assert page_score([], gpsr_complete=True, unit_price_required=False) == 100

    def test_gpsr_incomplete_costs_20(self):
        assert page_score([], gpsr_complete=False, unit_price_required=False) == 80

    def test_unit_price_missing_costs_10(self):
        assert page_score([], gpsr_complete=True, unit_price_required=True, unit_price_complete=False) == 90

    def test_unit_price_not_required_no_penalty(self):
        assert page_score([], gpsr_complete=True, unit_price_required=False, unit_price_complete=False) == 100

    def test_combined_penalties(self):
        findings = [Finding(rule_id="X", severity="block", text="t")]
        score = page_score(findings, gpsr_complete=False, unit_price_required=True, unit_price_complete=False)
        assert score == 100 - 25 - 20 - 10  # 45


# ── Publish gate tests ────────────────────────────────────────────────────


class TestPublishGate:
    def test_no_block_findings(self):
        findings = [Finding(rule_id="SUPERLATIVE", severity="warn", text="t")]
        assert has_open_block(findings) is False

    def test_has_block_finding(self):
        findings = [Finding(rule_id="MED_CLAIM", severity="block", text="t")]
        assert has_open_block(findings) is True

    def test_overridden_block_not_blocking(self):
        findings = [Finding(rule_id="MED_CLAIM", severity="block", text="t", override_reason="ok")]
        assert has_open_block(findings) is False
