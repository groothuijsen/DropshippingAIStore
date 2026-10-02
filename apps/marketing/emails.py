"""Transactional marketing email via Resend (T-155). Skips silently without key."""

import json
import urllib.request

from django.conf import settings


def send_email(to: str, subject: str, html: str) -> bool:
    if not settings.RESEND_API_KEY:
        return False
    body = json.dumps({
        "from": settings.MARKETING_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "html": html,
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False
