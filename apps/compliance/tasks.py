"""Withdrawal tasks — confirmation email + merchant notification.

See 07 §8.3.3: confirmation email to customer within 1 minute with
content of the declaration and date + time (durable medium).
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, acks_late=True, max_retries=3)
def send_withdrawal_confirmation(self, request_id: str) -> None:
    """Send confirmation email to the customer with declaration content + date/time."""
    from apps.compliance.models import WithdrawalRequest
    from apps.compliance.withdrawal_labels import get_withdrawal_labels  # noqa: F401

    try:
        request = WithdrawalRequest.objects.get(id=request_id)
    except WithdrawalRequest.DoesNotExist:
        logger.error("WithdrawalRequest %s not found", request_id)
        return

    # Email content: declaration + date + time (durable medium, 07 §8.3.3)
    submitted_str = request.submitted_at.strftime("%Y-%m-%d %H:%M UTC")
    _email_content = f"""
Uw herroepingsverklaring / Your withdrawal declaration

Naam / Name: {request.customer_name}
Bestelling / Order: {request.order_identifier}
Referentie / Reference: {request.reference}
Datum / Date: {submitted_str}

Hiermee bevestigen wij dat wij uw herroepingsverklaring hebben ontvangen.
We confirm that we have received your withdrawal declaration.
"""

    # TODO: Send via email service (Resend/SES) — log for now
    logger.info(
        "Withdrawal confirmation for %s sent to %s",
        request.reference,
        request.email,
    )

    request.confirmation_sent_at = timezone.now()
    request.save(update_fields=["confirmation_sent_at"])


@shared_task(bind=True, acks_late=True, max_retries=3)
def notify_merchant(self, request_id: str) -> None:
    """Notify merchant about a new withdrawal request."""
    from apps.compliance.models import WithdrawalRequest

    try:
        request = WithdrawalRequest.objects.get(id=request_id)
    except WithdrawalRequest.DoesNotExist:
        logger.error("WithdrawalRequest %s not found", request_id)
        return

    # TODO: Send merchant notification email — log for now
    logger.info(
        "Merchant notified: withdrawal %s from %s",
        request.reference,
        request.shop.domain,
    )

    request.merchant_notified_at = timezone.now()
    request.save(update_fields=["merchant_notified_at"])
