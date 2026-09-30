"""Legal page templates — draft templates per language (07 §7).

Until T-090 (lawyer review), pages show a draft banner.
Templates: withdrawal, impressum (DE only), GPSR/contact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.models import Shop

# Draft banner per language (07 §7)
DRAFT_BANNERS: dict[str, str] = {
    "nl": "Concept — laat controleren door een jurist voordat u publiceert.",
    "en": "Draft — have this reviewed by a lawyer before publishing.",
    "de": "Entwurf — vor der Veröffentlichung juristisch prüfen lassen.",
}

# Withdrawal template per language (07 §7, §8)
WITHDRAWAL_TEMPLATES: dict[str, str] = {
    "nl": """<h1>Herroepingsrecht</h1>
<p>U heeft het recht om binnen 14 dagen zonder opgave van redenen de overeenkomst te herroepen.</p>
<p>De herroepingstermijn verstrijkt 14 dagen na de dag waarop u of een door u aangewezen derde, die niet de vervoerder is, het goed fysiek in bezit krijgt.</p>
<h2>Modelformulier voor herroeping</h2>
<p>Aan: [Winkelnaam], [Adres], [E-mail]</p>
<p>Ik / Wij* deel/delen* u hierbij mede dat ik / wij* onze overeenkomst betreffende de verkoop van de volgende goederen / levering van de volgende dienst* herroep/herroepen*</p>
<p>Besteld op / ontvangen op* [datum]</p>
<p>Naam / namen consument(en)</p>
<p>Adres consument(en)</p>
<p>Handtekening consument(en) (alleen wanneer dit formulier op papier wordt ingediend)</p>
<p>* Doorhalen wat niet van toepassing is.</p>""",
    "de": """<h1>Widerrufsrecht</h1>
<p>Sie haben das Recht, binnen vierzehn Tagen ohne Angabe von Gründen diesen Vertrag zu widerrufen.</p>
<p>Die Widerrufsfrist beträgt vierzehn Tage ab dem Tag, an dem Sie oder ein von Ihnen benannter Dritter, der nicht der Beförderer ist, die Waren in Besitz genommen haben bzw. hat.</p>
<h2>Muster-Widerrufsformular</h2>
<p>An: [Shop-Name], [Adresse], [E-Mail]</p>
<p>Hiermit widerrufe(n) ich/wir* den von mir/uns* abgeschlossenen Vertrag über den Kauf der folgenden Waren / die Erbringung der folgenden Dienstleistung*</p>
<p>Bestellt am / erhalten am*</p>
<p>Name des/der Verbraucher(s)</p>
<p>Adresse des/der Verbraucher(s)</p>
<p>Unterschrift des/der Verbraucher(s) (nur bei Mitteilung auf Papier)</p>
<p>* Unzutreffendes streichen.</p>""",
    "en": """<h1>Right of Withdrawal</h1>
<p>You have the right to withdraw from this contract within 14 days without giving any reason.</p>
<p>The withdrawal period will expire after 14 days from the day on which you acquire, or a third party other than the carrier and indicated by you acquires, physical possession of the goods.</p>
<h2>Model withdrawal form</h2>
<p>To: [Shop name], [Address], [Email]</p>
<p>I/We* hereby give notice that I/We* withdraw from my/our* contract of sale of the following goods / provision of the following service*</p>
<p>Ordered on / received on*</p>
<p>Name of consumer(s)</p>
<p>Address of consumer(s)</p>
<p>Signature of consumer(s) (only if this form is notified on paper)</p>
<p>* Delete as appropriate.</p>""",
}

# Impressum template (DE only, 07 §7)
IMPRESSUM_TEMPLATES: dict[str, str] = {
    "de": """<h1>Impressum</h1>
<p>Angaben gemäß § 5 DDG</p>
<p>[Winkelname]</p>
<p>[Straße und Hausnummer]</p>
<p>[PLZ und Ort]</p>
<p>Land: [Land]</p>
<p>E-Mail: [E-Mail]</p>
<p>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV: [Name], [Adresse]</p>
<p>Verbraucherstreitbeilegung/Universalschlichtungsstelle:</p>
<p>Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>""",
}

# GPSR/contact template (07 §7)
GPSR_CONTACT_TEMPLATES: dict[str, str] = {
    "nl": """<h1>Contact & GPSR</h1>
<p>Neem contact met ons op via: [E-mail]</p>
<p>Wij zijn de verantwoordelijke verkoper voor producten die via deze winkel worden verkocht.</p>
<p>Voor fabrikantsinformatie per product: zie de GPSR-sectie op de productpagina.</p>""",
    "de": """<h1>Kontakt & GPSR</h1>
<p>Kontaktieren Sie uns unter: [E-Mail]</p>
<p>Wir sind der verantwortliche Verkäufer für die in diesem Shop verkauften Produkte.</p>
<p>Herstellerinformationen pro Produkt: siehe GPSR-Bereich auf der Produktseite.</p>""",
    "en": """<h1>Contact & GPSR</h1>
<p>Contact us at: [E-mail]</p>
<p>We are the responsible seller for products sold through this store.</p>
<p>For manufacturer information per product: see the GPSR section on the product page.</p>""",
}


def fill_template(template: str, shop: Shop) -> str:
    """Fill merchant details into a legal template.

    Replaces [Winkelnaam]/[Shop-Name]/[Shop name], [E-mail], etc.
    """
    result = template
    result = result.replace("[Winkelnaam]", shop.name)
    result = result.replace("[Shop-Name]", shop.name)
    result = result.replace("[Shop name]", shop.name)
    result = result.replace("[E-mail]", shop.email or "[E-mail]")
    result = result.replace("[Email]", shop.email or "[Email]")
    return result


def get_legal_pages(shop: Shop, locale: str) -> list[dict[str, str]]:
    """Get legal pages for a shop and locale.

    Returns list of dicts with: key, title, html_content, is_draft.
    """
    pages = []

    # Withdrawal page (all languages)
    if locale in WITHDRAWAL_TEMPLATES:
        html = fill_template(WITHDRAWAL_TEMPLATES[locale], shop)
        pages.append(
            {
                "key": "withdrawal",
                "title": "Herroepingsrecht"
                if locale == "nl"
                else ("Widerrufsrecht" if locale == "de" else "Right of Withdrawal"),
                "html_content": DRAFT_BANNERS.get(locale, DRAFT_BANNERS["en"]) + html,
                "is_draft": True,
            }
        )

    # Impressum (DE only)
    if locale == "de" and locale in IMPRESSUM_TEMPLATES:
        html = fill_template(IMPRESSUM_TEMPLATES[locale], shop)
        pages.append(
            {
                "key": "impressum",
                "title": "Impressum",
                "html_content": DRAFT_BANNERS.get(locale, DRAFT_BANNERS["en"]) + html,
                "is_draft": True,
            }
        )

    # GPSR/contact page
    if locale in GPSR_CONTACT_TEMPLATES:
        html = fill_template(GPSR_CONTACT_TEMPLATES[locale], shop)
        pages.append(
            {
                "key": "gpsr_contact",
                "title": "Contact & GPSR",
                "html_content": DRAFT_BANNERS.get(locale, DRAFT_BANNERS["en"]) + html,
                "is_draft": True,
            }
        )

    return pages


# Onboarding checklist for withdrawal (07 §8.4)
WITHDRAWAL_CHECKLIST: list[dict] = [
    {
        "id": "self_service_returns",
        "label": {
            "nl": "Zelfservice retouren ingeschakeld",
            "de": "Self-Service-Rückgaben aktiviert",
            "en": "Self-service returns enabled",
        },
        "deep_link": "https://admin.shopify.com/store/{domain}/settings/checkout",
    },
    {
        "id": "cancellation_policy",
        "label": {
            "nl": "Annuleringsbeleid: 'Totdat het item is verzonden'",
            "de": "Stornierungsrichtlinie: 'Bis der Artikel versendet wird'",
            "en": "Cancellation policy: 'Until item is shipped'",
        },
        "deep_link": "https://admin.shopify.com/store/{domain}/settings/policies",
    },
    {
        "id": "return_window",
        "label": {
            "nl": "Retourtermijn ≥ 14 dagen vanaf 'Levering van het laatste item in de bestelling'",
            "de": "Rückgabefrist ≥ 14 Tage ab 'Lieferung des letzten Artikels in der Bestellung'",
            "en": "Return window ≥ 14 days from 'Delivery of last item in order'",
        },
        "deep_link": "https://admin.shopify.com/store/{domain}/settings/policies",
    },
    {
        "id": "extend_weekends",
        "label": {
            "nl": "Verleng voor weekenden/feestdagen",
            "de": "Für Wochenenden/Feiertage verlängern",
            "en": "Extend for weekends/public holidays",
        },
        "deep_link": "https://admin.shopify.com/store/{domain}/settings/policies",
    },
]


def get_withdrawal_checklist(shop_domain: str, locale: str) -> list[dict[str, str]]:
    """Get the withdrawal onboarding checklist with working deep links.

    shop_domain: e.g. "test-store.myshopify.com" (used for admin deep links).
    """
    result = []
    for item in WITHDRAWAL_CHECKLIST:
        label = item["label"]
        result.append(
            {
                "id": item["id"],
                "label": label.get(locale, label["en"]) if isinstance(label, dict) else label,
                "deep_link": item["deep_link"].format(domain=shop_domain.replace(".myshopify.com", "")),
            }
        )
    return result
