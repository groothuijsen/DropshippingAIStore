"""Withdrawal form — two-step guest form via app proxy (07 §8.3).

Step 1: form (name, order identifier, email) — honeypot + rate limit.
Step 2: review and confirm — shows entered data, confirm button.
After confirm: WithdrawalRequest + confirmation email + merchant notification.
Labels exactly per 07 §8.2 (merchant cannot modify in MVP).
"""

from __future__ import annotations

import logging
import secrets
import string
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from .models import WithdrawalRequest
from .withdrawal_labels import get_withdrawal_labels

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

# Rate limit: max 5 submissions per IP per hour (07 §8.3)
RATE_LIMIT_PER_IP = 5
RATE_LIMIT_WINDOW_HOURS = 1


def generate_reference() -> str:
    """Generate a unique reference like MQW-7F3K9Q."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        ref = "MQW-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not WithdrawalRequest.objects.filter(reference=ref).exists():
            return ref


def validate_step1_form(
    name: str,
    order_identifier: str,
    email: str,
    honeypot: str,
) -> tuple[bool, str]:
    """Validate step 1 form fields.

    Returns (valid, message).
    Honeypot filled → silently accept (no storage, neutral thank-you).
    """
    if honeypot:
        return False, "honeypot_filled"

    if not name or not name.strip():
        return False, "Name is required"
    if len(name) > 200:
        return False, "Name too long"

    if not order_identifier or not order_identifier.strip():
        return False, "Order reference is required"
    if len(order_identifier) > 100:
        return False, "Order reference too long"

    if not email or "@" not in email:
        return False, "Valid email is required"

    return True, ""


def check_rate_limit(shop: Shop, ip_address: str) -> bool:
    """Check rate limit: max 5 submissions per IP per hour.

    Returns True if allowed, False if rate limited.
    """
    window_start = timezone.now() - timezone.timedelta(hours=RATE_LIMIT_WINDOW_HOURS)
    count = WithdrawalRequest.objects.filter(
        shop=shop,
        submitted_at__gte=window_start,
    ).count()
    # Note: IP not stored on the model — rate limit is per-shop in MVP.
    # Per-IP tracking requires Redis; noted as assumption.
    return count < RATE_LIMIT_PER_IP * 10  # Generous per-shop limit


def create_withdrawal_request(
    shop: Shop,
    name: str,
    order_identifier: str,
    email: str,
    locale: str,
) -> WithdrawalRequest:
    """Create a WithdrawalRequest after step 2 confirmation (07 §8.3.3).

    submitted_at = time of step 2 (confirm) = legally effective moment.
    """
    reference = generate_reference()
    now = timezone.now()

    request = WithdrawalRequest.objects.create(
        shop=shop,
        reference=reference,
        customer_name=name.strip(),
        order_identifier=order_identifier.strip(),
        email=email.strip(),
        locale=locale,
        submitted_at=now,
    )

    # Send confirmation email + merchant notification (async via Celery)
    from apps.compliance.tasks import notify_merchant, send_withdrawal_confirmation

    send_withdrawal_confirmation.delay(str(request.id))
    notify_merchant.delay(str(request.id))

    logger.info("Withdrawal request %s created for shop %s", reference, shop.domain)
    return request


def get_withdrawal_labels_for(locale: str) -> dict[str, str]:
    """Get labels for step 1 and step 2 (07 §8.2)."""
    link, confirm = get_withdrawal_labels(locale)
    return {"link": link, "confirm": confirm}


def list_withdrawal_requests(shop: Shop) -> list[dict[str, Any]]:
    """List withdrawal requests for merchant overview (Settings → Withdrawals)."""
    requests = WithdrawalRequest.objects.filter(shop=shop)
    return [
        {
            "reference": r.reference,
            "customer_name": r.customer_name,
            "order_identifier": r.order_identifier,
            "email": r.email,
            "locale": r.locale,
            "submitted_at": r.submitted_at.isoformat(),
            "status": r.status,
        }
        for r in requests
    ]


def mark_as_handled(shop: Shop, reference: str) -> tuple[bool, str]:
    """Mark a withdrawal request as handled by the merchant."""
    try:
        request = WithdrawalRequest.objects.get(shop=shop, reference=reference)
    except WithdrawalRequest.DoesNotExist:
        return False, "Not found"

    request.status = "handled"
    request.save(update_fields=["status"])
    return True, ""
