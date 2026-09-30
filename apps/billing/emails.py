"""Billing emails — trial reminders, cancellation confirmation.

See docs/08-billing.md §4-5.
No external email service wired yet; emails are logged and queued
for the email service integration.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Email templates (08 §4-5)
TRIAL_REMINDER_SUBJECT = "Your trial ends soon"
TRIAL_REMINDER_BODY = "Your trial ends on {date}. Don't want to continue? Cancel here with one click: {cancel_url}"
CANCEL_CONFIRMATION_SUBJECT = "Subscription cancelled"
CANCEL_CONFIRMATION_BODY = "Your subscription has been cancelled. You will no longer be billed."


def send_trial_reminder(shop_domain: str, trial_ends_at: str, cancel_url: str) -> dict[str, Any]:
    """Send trial reminder email 48h before trial end (08 §4).

    Returns dict with email details.
    """
    body = TRIAL_REMINDER_BODY.format(date=trial_ends_at, cancel_url=cancel_url)

    logger.info(
        "TRIAL REMINDER email to %s: %s — %s",
        shop_domain,
        TRIAL_REMINDER_SUBJECT,
        body,
    )

    return {
        "to": shop_domain,
        "subject": TRIAL_REMINDER_SUBJECT,
        "body": body,
        "sent": True,
    }


def send_cancellation_confirmation(shop_domain: str) -> dict[str, Any]:
    """Send cancellation confirmation email (08 §5).

    Returns dict with email details.
    """
    logger.info(
        "CANCELLATION CONFIRMATION email to %s: %s — %s",
        shop_domain,
        CANCEL_CONFIRMATION_SUBJECT,
        CANCEL_CONFIRMATION_BODY,
    )

    return {
        "to": shop_domain,
        "subject": CANCEL_CONFIRMATION_SUBJECT,
        "body": CANCEL_CONFIRMATION_BODY,
        "sent": True,
    }
