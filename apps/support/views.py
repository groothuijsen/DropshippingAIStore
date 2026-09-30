"""Support views — contact form, status page link, FAQ.

See docs/09-ui-screens.md (GET /app/support/).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .forms import ContactForm

logger = logging.getLogger(__name__)

SUPPORT_EMAIL = getattr(settings, "SUPPORT_EMAIL", "support@mosaiq.app")

# FAQ content (nl/en/de)
FAQ_ITEMS: list[dict] = [
    {
        "id": "how_to_start",
        "question": {
            "nl": "Hoe start ik met Mosaiq?",
            "de": "Wie starte ich mit Mosaiq?",
            "en": "How do I get started with Mosaiq?",
        },
        "answer": {
            "nl": "Doorloop de onboarding: kies je taal, stel je merk in, importeer je bron en activeer het thema. Daarna kun je producten selecteren en pagina's genereren.",
            "de": "Durchlaufen Sie das Onboarding: Sprache wählen, Marke einrichten, Quelle importieren, Theme aktivieren. Danach können Sie Produkte auswählen und Seiten generieren.",
            "en": "Go through onboarding: choose your language, set up your brand, import your source, activate the theme. Then select products and generate pages.",
        },
    },
    {
        "id": "ai_images",
        "question": {
            "nl": "Zijn de AI-afbeeldingen EU-conform?",
            "de": "Sind die KI-Bilder EU-konform?",
            "en": "Are the AI images EU-compliant?",
        },
        "answer": {
            "nl": "Ja. Elke gepubliceerde AI-afbeelding heeft een C2PA-manifest en een zichtbaar label 'Afbeelding gemaakt met AI' (standaard aan).",
            "de": "Ja. Jedes veröffentlichte KI-Bild hat ein C2PA-Manifest und ein sichtbares Label 'Mit KI erstellt' (standardmäßig aktiviert).",
            "en": "Yes. Every published AI image has a C2PA manifest and a visible label 'Image made with AI' (on by default).",
        },
    },
    {
        "id": "withdrawal_form",
        "question": {
            "nl": "Hoe werkt het herroepingsformulier?",
            "de": "Wie funktioniert das Widerrufsformular?",
            "en": "How does the withdrawal form work?",
        },
        "answer": {
            "nl": "Klanten vullen het formulier in via /apps/mosaiq/withdraw. Na bevestiging ontvangen ze een e-mail met de verklaring en datum. Je vindt alle aanvragen onder Instellingen → Herroepingen.",
            "de": "Kunden füllen das Formular über /apps/mosaiq/withdraw aus. Nach der Bestätigung erhalten sie eine E-Mail mit der Erklärung und dem Datum. Alle Anträge finden Sie unter Einstellungen → Widerrufe.",
            "en": "Customers fill in the form at /apps/mosaiq/withdraw. After confirming they receive an email with the declaration and date. All requests are under Settings → Withdrawals.",
        },
    },
    {
        "id": "billing",
        "question": {
            "nl": "Hoe beheer ik mijn abonnement?",
            "de": "Wie verwalte ich mein Abo?",
            "en": "How do I manage my subscription?",
        },
        "answer": {
            "nl": "Ga naar Instellingen → Abonnement. Je kunt upgraden, downgraden of opzeggen. Opzegging gebeurt via Shopify en is direct actief.",
            "de": "Gehen Sie zu Einstellungen → Abo. Sie können upgraden, downgraden oder kündigen. Die Kündigung erfolgt über Shopify und ist sofort wirksam.",
            "en": "Go to Settings → Subscription. You can upgrade, downgrade or cancel. Cancellation happens via Shopify and is immediate.",
        },
    },
    {
        "id": "compliance_score",
        "question": {
            "nl": "Wat is de compliance-score?",
            "de": "Was ist der Compliance-Score?",
            "en": "What is the compliance score?",
        },
        "answer": {
            "nl": "De compliance-score meet hoe volledig een pagina voldoet aan EU-regels: claims, GPSR, eenheidsprijs, Omnibus-prijzen. Een score van 100 betekent dat alles aanwezig is.",
            "de": "Der Compliance-Score misst, wie vollständig eine Seite EU-Vorschriften erfüllt: Claims, GPSR, Grundpreis, Omnibus-Preise. Ein Score von 100 bedeutet, dass alles vorhanden ist.",
            "en": "The compliance score measures how completely a page meets EU rules: claims, GPSR, unit price, Omnibus pricing. A score of 100 means everything is present.",
        },
    },
]


def index(request: HttpRequest) -> HttpResponse:
    """Support page — contact form, status link, FAQ."""
    locale = getattr(request, "shop", None)
    locale_code = getattr(locale, "primary_locale", "en") if locale else "en"

    form = ContactForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        subject = form.cleaned_data["subject"]
        message = form.cleaned_data["message"]
        shop_domain = form.cleaned_data.get("shop_domain", "")

        full_message = f"Winkel / Shop: {shop_domain}\n\n{message}"

        try:
            send_mail(
                subject=f"[Mosaiq Support] {subject}",
                message=full_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[SUPPORT_EMAIL],
                fail_silently=False,
            )
            logger.info("Support email sent for shop %s", shop_domain)
        except Exception as exc:
            logger.error("Failed to send support email: %s", exc)

        return HttpResponse(
            '<div class="mq-success">Bedankt! We nemen zo snel mogelijk contact op. / Thank you! We will get back to you as soon as possible.</div>',
            content_type="text/html",
        )

    faq = [
        {
            "id": item["id"],
            "question": item["question"].get(locale_code, item["question"]["en"]),
            "answer": item["answer"].get(locale_code, item["answer"]["en"]),
        }
        for item in FAQ_ITEMS
    ]

    return render(
        request,
        "support/index.html",
        {
            "form": form,
            "faq": faq,
            "status_url": "https://status.mosaiq.app",
        },
    )
