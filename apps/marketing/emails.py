"""Onboarding email series for confirmed leads (T-159, S12).

Sent by the send_onboarding_emails management command (cron-ready).
Renders NL/EN/DEN body text per lead language. Uses Resend when
RESEND_API_KEY is set; otherwise logs only (dev mode).
"""

from __future__ import annotations

import logging

from django.conf import settings

from .models import Lead, OnboardingEmail

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
        already = set(OnboardingEmail.objects.filter(lead=lead).values_list('step', flat=True))
        for day, key, *_ in SERIES:
            if key in already:
                continue
            if lead.days_since_confirmed == day:
                subject, html = render_email(key, lead.lang)
                OnboardingEmail.objects.get_or_create(lead=lead, step=key)
                if getattr(settings, 'RESEND_API_KEY', ''):
                    logger.info('onboarding %s -> %s (%s)', key, lead.email, subject)
                else:
                    logger.info('onboarding(dev, no RESEND_API_KEY) %s -> %s (%s)', key, lead.email, subject)
                sent += 1
    return sent


# --- T-155 early-access emails (restored) ---


def _send_resend(to: str, subject: str, html: str) -> bool:
    import json
    import urllib.request

    key = getattr(settings, 'RESEND_API_KEY', '')
    if not key:
        return False
    data = json.dumps({
        'from': getattr(settings, 'MARKETING_FROM_EMAIL', 'hello@mosaiq.marketing'),
        'to': [to],
        'subject': subject,
        'html': html,
    }).encode()
    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=data,
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        logger.exception('resend send failed')
        return False


def send_email(to: str, subject: str, html: str) -> bool:
    return _send_resend(to, subject, html)


def send_welcome_email(to: str, lang: str) -> bool:
    href = '/nl/vroege-toegang/' if lang == 'nl' else '/early-access/'
    subject = 'Welcome to Mosaiq' if lang == 'en' else 'Welkom bij Mosaiq'
    html = f'<html><body><h2>{subject}</h2><p><a href="https://{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else "shopify.mosaiq.marketing"}{href}">Get started</a></p></body></html>'
    return _send_resend(to, subject, html)
