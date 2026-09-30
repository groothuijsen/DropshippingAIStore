"""Billing cancellation — in-app cancel + Shopify cancel + confirmation email.

See docs/08-billing.md §5, docs/specs/F12-billing.md criterion 8.
Cancelling in the app → appSubscriptionCancel(id, prorate:true) + confirmation email.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.shopify_client import ShopifyGraphQLClient, load_query

from .emails import send_cancellation_confirmation
from .models import Subscription  # noqa: TC001

logger = logging.getLogger(__name__)


def cancel_subscription(shop: Any, subscription: Subscription) -> tuple[bool, str, dict[str, Any]]:
    """Cancel a subscription in the app (08 §5, F12 criterion 8).

    1. appSubscriptionCancel(id, prorate: true)
    2. Update Subscription.status = cancelled
    3. Send confirmation email

    Returns (success, message, result_dict).
    """
    from apps.core.crypto import decrypt_token
    from apps.core.models import ShopStatus

    if shop.status != ShopStatus.ACTIVE:
        return False, "Shop not active", {}

    if not subscription.shopify_subscription_gid:
        return False, "No Shopify subscription GID", {}

    token = decrypt_token(shop.access_token_encrypted)
    client = ShopifyGraphQLClient(
        shop_domain=shop.domain,
        access_token=token,
        api_version="2026-07",
    )

    try:
        data = client.execute(
            load_query("subscription_cancel"),
            variables={
                "id": subscription.shopify_subscription_gid,
                "prorate": True,
            },
        )

        cancel_data = data.get("appSubscriptionCancel", {})
        user_errors = cancel_data.get("userErrors", [])
        if user_errors:
            error_msg = user_errors[0].get("message", "Unknown error")
            logger.warning("Subscription cancel failed for %s: %s", shop.domain, error_msg)
            return False, error_msg, {}

        sub_data = cancel_data.get("appSubscription", {})
        shopify_status = sub_data.get("status", "").lower()

        # Update local subscription
        subscription.status = "cancelled"
        subscription.save(update_fields=["status", "updated_at"])

        # Send confirmation email
        email_result = send_cancellation_confirmation(shop.domain)

        logger.info("Subscription cancelled for %s", shop.domain)
        return (
            True,
            "Subscription cancelled",
            {
                "shopify_status": shopify_status,
                "email": email_result,
            },
        )

    finally:
        client.close()
