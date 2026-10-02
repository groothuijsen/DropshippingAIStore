"""Fact blocks + assembly for standard pages (T-116, 12 §3, D-15.4).

The AI writes only intro/FAQ text; delivery times, costs and the return
address are inserted here from `DeliveryProfile` / `BusinessDetails`.
Missing facts produce explicit "missing" blocks — never invented data.
"""

from __future__ import annotations

import re

# Withdrawal page created by the legal app (07 §7) at go-live.
WITHDRAWAL_URL = "/pages/withdrawal"

DIGIT_RE = re.compile(r"\d")

_STRINGS = {
    "delivery_heading": {"en": "Delivery times", "nl": "Levertijden", "de": "Lieferzeiten"},
    "delivery_missing": {
        "en": "Delivery times missing — complete your delivery profile in Mosaiq.",
        "nl": "Levertijden ontbreken — vul je leverprofiel in Mosaiq aan.",
        "de": "Lieferzeiten fehlen — vervollständige dein Lieferprofil in Mosaiq.",
    },
    "ship_from": {"en": "Ship from", "nl": "Verzonden vanaf", "de": "Versand aus"},
    "working_days": {"en": "working days", "nl": "werkdagen", "de": "Werktage"},
    "incl_processing": {"en": "incl. processing", "nl": "inclusief verwerking", "de": "inkl. Bearbeitung"},
    "free_from": {"en": "free from", "nl": "gratis vanaf", "de": "kostenfrei ab"},
    "withdrawal_heading": {"en": "Right of withdrawal", "nl": "Herroepingsrecht", "de": "Widerrufsrecht"},
    "withdrawal_body": {
        "en": "You have the right to withdraw from this contract within 14 days, without giving any reason. Use the model withdrawal form:",
        "nl": "Je hebt het recht om deze overeenkomst binnen 14 dagen zonder opgave van redenen te herroepen. Gebruik het modelformulier voor herroeping:",
        "de": "Sie haben das Recht, diesen Vertrag innerhalb von 14 Tagen ohne Angabe von Gründen zu widerrufen. Nutzen Sie das Muster-Widerrufsformular:",
    },
    "return_heading": {"en": "Return address", "nl": "Retouradres", "de": "Rücksendeadresse"},
    "return_missing": {
        "en": "Return address missing — complete your business details in Mosaiq.",
        "nl": "Retouradres ontbrekend — vul je bedrijfsgegevens in Mosaiq aan.",
        "de": "Rücksendeadresse fehlt — vervollständige deine Geschäftsdaten in Mosaiq.",
    },
    "return_company_note": {
        "en": "Return to the company address above.",
        "nl": "Retourneer naar bovenstaand bedrijfsadres.",
        "de": "Senden Sie an die obige Firmenadresse zurück.",
    },
}


def _t(key: str, locale: str) -> str:
    return _STRINGS[key].get(locale, _STRINGS[key]["en"])


def _money(value) -> str:
    from decimal import Decimal

    return f"{Decimal(str(value)):.2f}"


def _profile_lines(profile, locale: str) -> list[str]:
    lines = []
    ship_from = profile.ship_from_country
    for market, span in (profile.transit_days or {}).items():
        min_days = profile.processing_days_min + span[0]
        max_days = profile.processing_days_max + span[1]
        line = (
            f"{market}: {min_days}–{max_days} {_t('working_days', locale)} "
            f"({_t('incl_processing', locale)})"
        )
        cost = (profile.shipping_cost or {}).get(market) or {}
        if cost.get("amount") is not None:
            line += f" — {_money(cost['amount'])}"
            if cost.get("free_from") is not None:
                line += f" ({_t('free_from', locale)} {_money(cost['free_from'])})"
        lines.append(line)
    header = f"{_t('ship_from', locale)} {ship_from}"
    return [header, *lines]


def build_fact_sections(shop, page_type: str, locale: str = "en") -> tuple[list[dict], list[str]]:
    """Return (sections, missing) for a standard page type.

    Sections are rich_text payloads in the 05 §3 shape; `missing` lists
    fact keys the merchant still has to provide (F18-10 go-live gate).
    """
    sections: list[dict] = []
    missing: list[str] = []

    if page_type == "shipping":
        profiles = list(shop.delivery_profiles.all().order_by("source_app"))
        if not profiles:
            sections.append(
                {
                    "type": "rich_text",
                    "heading": _t("delivery_heading", locale),
                    "body": _t("delivery_missing", locale),
                }
            )
            missing.append("delivery_profile")
        else:
            body_parts: list[str] = []
            for profile in profiles:
                body_parts.extend(_profile_lines(profile, locale))
            sections.append(
                {
                    "type": "rich_text",
                    "heading": _t("delivery_heading", locale),
                    "body": "\n".join(body_parts),
                }
            )

    if page_type == "returns":
        sections.append(
            {
                "type": "rich_text",
                "heading": _t("withdrawal_heading", locale),
                "body": f"{_t('withdrawal_body', locale)} {WITHDRAWAL_URL}",
            }
        )
        try:
            details = shop.business_details
        except Exception:  # OneToOne reverse: DoesNotExist when absent
            details = None
        if details is None:
            missing_bd = ["legal_name", "street", "postal_code", "city", "return_address"]
            sections.append(
                {
                    "type": "rich_text",
                    "heading": _t("return_heading", locale),
                    "body": _t("return_missing", locale),
                }
            )
            missing.extend(missing_bd)
        else:
            missing_bd = details.is_complete("returns")
            if missing_bd:
                sections.append(
                    {
                        "type": "rich_text",
                        "heading": _t("return_heading", locale),
                        "body": _t("return_missing", locale),
                    }
                )
                missing.extend(missing_bd)
            else:
                address = details.return_address or (
                    f"{details.street}\n{details.postal_code} {details.city}\n{details.country_code}"
                )
                body = f"{details.legal_name}\n{address}"
                if details.return_address_same or not details.return_address:
                    body = f"{details.legal_name}\n{address}\n{_t('return_company_note', locale)}"
                sections.append(
                    {
                        "type": "rich_text",
                        "heading": _t("return_heading", locale),
                        "body": body,
                    }
                )

    return sections, missing


def assemble_standard_pages(shop, page_types: list[str], ai_pages: list[dict], locale: str = "en") -> dict:
    """Merge AI intro/faq with code-inserted fact blocks (12 §3 rules)."""
    ai_by_type = {p.get("page_type"): p for p in ai_pages}
    result: dict[str, dict] = {}

    for page_type in page_types:
        ai = ai_by_type.get(page_type)
        warnings: list[str] = []
        if ai is None:
            result[page_type] = {"title": page_type.title(), "sections": [], "warnings": ["not_generated"]}
            continue

        fact_sections, missing = build_fact_sections(shop, page_type, locale)
        intro_section = {
            "type": "rich_text",
            "heading": "",
            "body": ai.get("intro", ""),
        }
        faq_section = {
            "type": "faq",
            "items": [
                {"question": item.get("question", ""), "answer": item.get("answer", "")}
                for item in ai.get("faq_items", [])
            ],
        }

        if page_type == "faq":
            sections = [intro_section, faq_section]
        elif page_type == "shipping" or page_type == "returns":
            sections = [intro_section, *fact_sections, faq_section]
        else:  # about and anything else: intro + optional faq
            sections = [intro_section]
            if ai.get("faq_items"):
                sections.append(faq_section)

        if missing:
            warnings.append("missing_facts:" + ",".join(sorted(set(missing))))

        result[page_type] = {
            "title": ai.get("title") or page_type.title(),
            "sections": sections,
            "warnings": warnings,
        }

    return result


def ai_text_has_numbers(ai_pages: list[dict]) -> bool:
    """F15-16: AI text may not contain digits outside inserted fact blocks."""
    for page in ai_pages:
        for field in (page.get("title"), page.get("intro")):
            if field and DIGIT_RE.search(field):
                return True
        for item in page.get("faq_items", []):
            if DIGIT_RE.search(item.get("question", "")) or DIGIT_RE.search(item.get("answer", "")):
                return True
    return False
