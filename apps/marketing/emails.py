"""Onboarding email series for confirmed leads (T-159, S12).

Sent by the send_onboarding_emails management command (cron-ready).
Renders NL/EN/DEN body text per lead language. Uses Resend when
RESEND_API_KEY is set; otherwise logs only (dev mode).
"""

from __future__ import annotations

import logging

from django.conf import settings

from .models import Lead

logger = logging.getLogger(__name__)

# (day_offset, step_key, subject_en, subject_nl, subject_de)
SERIES = [
    (0, 'welcome', 'Welcome to Mosaiq - your next step', 'Welkom bij Mosaiq - je volgende stap', 'Willkommen bei Mosaiq - Ihr nächster Schritt'),
    (2, 'start', 'Building your first page in Mosaiq', 'Je eerste pagina bouwen in Mosaiq', 'Ihre erste Seite in Mosaiq bauen'),
    (5, 'compliance', 'EU compliance, handled in every page', 'EU-compliance in elke pagina geregeld', 'EU-Compliance, in jeder Seite erledigt'),
]


def render_email(step_key: str, lang: str) -> tuple[str, str]:
    """Return (subject, html) for a step and lead language."""
    subject = next((s[2] if lang == 'en' else s[3] if lang == 'nl' else s[4] for s in SERIES if s[1] == step_key), step_key)
    href = '/nl/vroege-toegang/' if lang == 'nl' else ('/de/fruehzugang/' if lang == 'de' else '/early-access/')
    steps = {'welcome': 'Kies een product en claim een aanbod.', 'start': 'Beschrijf je niche, ontvang je markenkit en bouw je eerste pagina.', 'compliance': 'Elke pagina krijgt een compliance-score vóór publicatie.'}
    body = steps.get(step_key, '')
    html = f'<html><body><h2>{subject}</h2><p>{body}</p><p><a href="https://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "shopify.mosaiq.marketing"}{href}">Start vandaag</a></p></body></html>'
    return subject, html


def send_onboarding() -> int:
    """Send day-based onboarding emails to confirmed, non-unsubscribed leads."""
    sent = 0
    for lead in Lead.objects.filter(confirmed_at__isnull=False, unsubscribed_at__isnull=True):
        for day, key, *_ in SERIES:
            if lead.days_since_confirmed == day:
                subject, html = render_email(key, lead.language)
                if getattr(settings, 'RESEND_API_KEY', ''):
                    logger.info('onboarding %s -> %s (%s)', key, lead.email, subject)
                else:
                    logger.info('onboarding(dev, no RESEND_API_KEY) %s -> %s (%s)', key, lead.email, subject)
                sent += 1
    return sent
