"""Claims blocklist — deterministic claim detection per language.

See docs/07-compliance.md §4.1.
Case-insensitive, word boundaries. Match → Finding with rule_id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Finding:
    """A single compliance finding."""

    rule_id: str
    severity: str  # "block" or "warn"
    text: str
    section_index: int = 0
    field_path: str = ""
    locale: str = "nl"
    source: str = "deterministic"  # deterministic or ai
    override_reason: str = ""

    @property
    def is_block(self) -> bool:
        return self.severity == "block"

    @property
    def is_warn(self) -> bool:
        return self.severity == "warn"


# Blocklist per language (07 §4.1)
# rule_id → {severity, patterns per language}
BLOCKLIST: dict[str, dict[str, Any]] = {
    "EMPCO_GENERIC": {
        "severity": "block",
        "patterns": {
            "nl": [
                "duurzaam",
                "milieuvriendelijk",
                "eco",
                "ecologisch",
                "klimaatneutraal",
                "CO2-neutraal",
                "natuurvriendelijk",
                "planeetvriendelijk",
            ],
            "en": [
                "sustainable",
                "eco-friendly",
                "eco",
                "green",
                "environmentally friendly",
                "climate neutral",
                "carbon neutral",
                "planet-friendly",
                "nature-friendly",
            ],
            "de": ["nachhaltig", "umweltfreundlich", "öko", "grün", "klimaneutral", "CO2-neutral", "naturfreundlich"],
        },
    },
    "MED_CLAIM": {
        "severity": "block",
        "patterns": {
            "nl": [
                "geneest",
                "behandelt",
                "verhelpt",
                "tegen slapeloosheid",
                "tegen angst",
                "pijnverlichting",
                "klinisch bewezen",
                "medisch getest",
            ],
            "en": [
                "cures",
                "treats",
                "heals",
                "relieves insomnia",
                "anti-anxiety",
                "pain relief",
                "clinically proven",
                "medically tested",
            ],
            "de": [
                "heilt",
                "behandelt",
                "lindert Schlaflosigkeit",
                "gegen Angst",
                "Schmerzlinderung",
                "klinisch bewiesen",
                "medizinisch getestet",
            ],
        },
    },
    "FAKE_URGENCY": {
        "severity": "block",
        "patterns": {
            "nl": ["alleen vandaag", "bijna uitverkocht", "laatste kans", "op=op"],
            "en": ["only today", "almost sold out", "last chance", "while stocks last"],
            "de": ["nur heute", "fast ausverkauft", "letzte Chance", "solange der Vorrat reicht"],
        },
    },
    "FAKE_SOCIAL": {
        "severity": "block",
        "patterns": {
            "nl": ["bestseller", "tevreden klanten", "bekend van"],
            "en": ["bestseller", "happy customers", "as seen on"],
            "de": ["Bestseller", "zufriedene Kunden", "bekannt aus"],
        },
    },
    "SUPERLATIVE": {
        "severity": "warn",
        "patterns": {
            "nl": ["de beste", "nummer 1", "perfect", "gegarandeerd resultaat"],
            "en": ["the best", "#1", "perfect", "guaranteed results"],
            "de": ["das beste", "Nr. 1", "perfekt", "garantiert"],
        },
    },
    "AUTO_ROADLEGAL": {
        "severity": "block",
        "niche": "auto_accessories",
        "patterns": {
            "nl": ["straatlegaal", "E-keur", "RDW-goedgekeurd", "toegestaan op de openbare weg"],
            "en": ["road legal", "E-approved", "street legal"],
            "de": ["straßenzugelassen", "E-Prüfzeichen", "TÜV-geprüft", "StVZO-konform"],
        },
    },
}

# Valid rule_ids (AI-only rules included)
VALID_RULE_IDS = {
    "EMPCO_GENERIC",
    "MED_CLAIM",
    "FAKE_URGENCY",
    "FAKE_SOCIAL",
    "SUPERLATIVE",
    "AUTO_ROADLEGAL",
    "EMPCO_LABEL",
    "UNSUPPORTED_FACT",
    "IP_REFERENCE",
    "SHIPPING_CLAIM",
}


def _build_pattern(pattern: str) -> re.Pattern[str]:
    """Build a word-boundary regex pattern."""
    return re.compile(r"\b" + re.escape(pattern) + r"\b", re.IGNORECASE)


def check_claims(
    text: str,
    locale: str,
    section_index: int = 0,
    field_path: str = "",
    niche: str = "",
    facts: list[str] | None = None,
    delivery: dict[str, Any] | None = None,
) -> list[Finding]:
    """Check text against the deterministic blocklist.

    `delivery` is the product's estimate context (F18-8):
    {"max_days": int, "ship_from": str} or None when no estimate exists.
    """
    findings: list[Finding] = []
    if not text:
        return findings

    for rule_id, rule in BLOCKLIST.items():
        # Skip niche-specific rules if not applicable
        if "niche" in rule and rule["niche"] != niche:
            continue

        patterns = rule.get("patterns", {}).get(locale, [])
        severity = rule["severity"]

        for pattern in patterns:
            regex = _build_pattern(pattern)
            if regex.search(text):
                # EMPCO_GENERIC exception: if sentence contains specific fact → warn
                if rule_id == "EMPCO_GENERIC" and facts and any(f.lower() in text.lower() for f in facts):
                    severity = "warn"

                findings.append(
                    Finding(
                        rule_id=rule_id,
                        severity=severity,
                        text=text,
                        section_index=section_index,
                        field_path=field_path,
                        locale=locale,
                    )
                )
                break  # One finding per rule per text

    # SHIPPING_CLAIM (12 §8, F18-8): fast-delivery phrases are block when
    # the product's max_days > 3, warn when no estimate exists; "ships from
    # EU" claims block unless ship_from is an EU member state.
    findings.extend(
        _check_shipping_claims(text, locale, delivery, section_index, field_path)
    )

    return findings


# EU member states (ISO 3166-1 alpha-2) — for the "ships from EU" claim.
EU_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
}

# locale → fast-delivery phrase patterns (12 §8).
SHIPPING_CLAIM_PATTERNS: dict[str, list[str]] = {
    "nl": ["snelle levering", "morgen in huis", "binnen 24 uur"],
    "en": ["fast shipping", "next-day delivery", "ships in 24 hours"],
    "de": ["schnelle lieferung", "morgen geliefert", "lieferung in 24 stunden"],
}

EU_SHIP_PATTERNS: dict[str, list[str]] = {
    "nl": ["eu-magazijn", "vanuit europa", "uit eu"],
    "en": ["eu warehouse", "ships from europe", "from the eu"],
    "de": ["eu-lager", "versand aus europa", "aus der eu"],
}


def _check_shipping_claims(
    text: str,
    locale: str,
    delivery: dict[str, Any] | None,
    section_index: int,
    field_path: str,
) -> list[Finding]:
    """Context-aware delivery claim check (F18-8)."""
    max_days = (delivery or {}).get("max_days")
    ship_from = (delivery or {}).get("ship_from") or ""

    for pattern in SHIPPING_CLAIM_PATTERNS.get(locale, []):
        if _build_pattern(pattern).search(text):
            if max_days is None:
                severity = "warn"
            elif max_days > 3:
                severity = "block"
            else:
                return []  # claim is truthful — no finding
            return [
                Finding(
                    rule_id="SHIPPING_CLAIM",
                    severity=severity,
                    text=text,
                    section_index=section_index,
                    field_path=field_path,
                    locale=locale,
                )
            ]

    for pattern in EU_SHIP_PATTERNS.get(locale, []):
        if _build_pattern(pattern).search(text):
            if ship_from and ship_from.upper() in EU_COUNTRIES:
                return []  # claim is true
            return [
                Finding(
                    rule_id="SHIPPING_CLAIM",
                    severity="block",
                    text=text,
                    section_index=section_index,
                    field_path=field_path,
                    locale=locale,
                )
            ]

    return []


def check_sections(
    sections: list[dict[str, Any]],
    locale: str,
    niche: str = "",
    facts: list[str] | None = None,
    delivery: dict[str, Any] | None = None,
) -> list[Finding]:
    """Check all text fields in sections against the blocklist."""
    findings: list[Finding] = []

    for idx, section in enumerate(sections):
        section_type = section.get("type", "")
        for key, value in section.items():
            if key == "type":
                continue
            if isinstance(value, str):
                findings.extend(
                    check_claims(
                        value,
                        locale,
                        idx,
                        f"{section_type}.{key}",
                        niche,
                        facts,
                        delivery,
                    )
                )
            elif isinstance(value, list):
                for item_idx, item in enumerate(value):
                    if isinstance(item, str):
                        findings.extend(
                            check_claims(
                                item,
                                locale,
                                idx,
                                f"{section_type}.{key}[{item_idx}]",
                                niche,
                                facts,
                                delivery,
                            )
                        )
                    elif isinstance(item, dict):
                        for sub_key, sub_val in item.items():
                            if isinstance(sub_val, str):
                                findings.extend(
                                    check_claims(
                                        sub_val,
                                        locale,
                                        idx,
                                        f"{section_type}.{key}[{item_idx}].{sub_key}",
                                        niche,
                                        facts,
                                        delivery,
                                    )
                                )

    return findings


def validate_rule_id(rule_id: str) -> bool:
    """Validate that a rule_id is in the allowed set."""
    return rule_id in VALID_RULE_IDS
