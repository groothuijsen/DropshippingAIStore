"""Billing plan changes — upgrade/downgrade.

See docs/08-billing.md §2, docs/specs/F12-billing.md criterion 7.
Upgrade → replacementBehavior: APPLY_IMMEDIATELY
Downgrade → replacementBehavior: APPLY_ON_NEXT_BILLING_CYCLE
Downgrade leaves existing live pages in place (08 §1).
"""

from __future__ import annotations

import logging
from typing import Any

from apps.core.shopify_client import ShopifyGraphQLClient, load_query

from .models import Subscription  # noqa: TC001
from .plans import PLAN_NAMES, get_founding_price, get_plan_price

logger = logging.getLogger(__name__)

# Plan ordering for upgrade/downgrade detection
PLAN_ORDER = {"starter": 1, "pro": 2, "agency": 3}


def is_upgrade(current_plan: str, new_plan: str) -> bool:
    """Check if changing from current_plan to new_plan is an upgrade."""
    return PLAN_ORDER.get(new_plan, 0) > PLAN_ORDER.get(current_plan, 0)


def get_replacement_behavior(current_plan: str, new_plan: str) -> str:
    """Get the correct replacementBehavior for a plan change.

    Upgrade → APPLY_IMMEDIATELY
    Downgrade → APPLY_ON_NEXT_BILLING_CYCLE
    """
    if is_upgrade(current_plan, new_plan):
        return "APPLY_IMMEDIATELY"
    return "APPLY_ON_NEXT_BILLING_CYCLE"


def change_plan(
    shop: Any,
    subscription: Subscription,
    new_plan: str,
    interval: str = "every_30_days",
) -> tuple[bool, str, dict[str, Any]]:
    """Change the subscription plan (F12 criterion 7).

    1. Determine upgrade/downgrade
    2. appSubscriptionCreate with correct replacementBehavior
    3. Update Subscription.plan

    Returns (success, message, result_dict).
    """
    from apps.core.crypto import decrypt_token
    from apps.core.models import ShopStatus

    if shop.status != ShopStatus.ACTIVE:
        return False, "Shop not active", {}

    if new_plan not in PLAN_ORDER:
        return False, f"Unknown plan: {new_plan}", {}

    current_plan = subscription.plan
    upgrade = is_upgrade(current_plan, new_plan)
    replacement_behavior = get_replacement_behavior(current_plan, new_plan)

    # Get price — founding discount takes priority when active (T-160)
    founding = getattr(shop, "founding_discount", None)
    if founding is not None and founding.is_active:
        price = get_founding_price(new_plan, interval, founding.percent_off)
        logger.info("Founding discount applied for %s: %s%% off → %s", shop.domain, founding.percent_off, price)
    else:
        price = get_plan_price(new_plan, interval)

    # Build line item
    line_item = {
        "plan": {
            "appRecurringPricingDetails": {
                "price": {
                    "amount": str(price),
                    "currencyCode": shop.currency_code,
                },
                "interval": interval.upper().replace("EVERY_30_DAYS", "EVERY_30_DAYS"),
            }
        }
    }

    # Map interval to Shopify enum
    shopify_interval = "EVERY_30_DAYS" if interval == "every_30_days" else "ANNUAL"
    line_item["plan"]["appRecurringPricingDetails"]["interval"] = shopify_interval

    # Build plan name
    plan_name = PLAN_NAMES.get(new_plan, f"Mosaiq {new_plan.title()}")
    if interval == "annual":
        plan_name += " (annual)"

    token = decrypt_token(shop.access_token_encrypted)
    client = ShopifyGraphQLClient(
        shop_domain=shop.domain,
        access_token=token,
        api_version="2026-07",
    )

    try:
        store_handle = shop.domain.replace(".myshopify.com", "")
        return_url = f"https://admin.shopify.com/store/{store_handle}/apps/mosaiq/billing/return"

        data = client.execute(
            load_query("subscription_create"),
            variables={
                "name": plan_name,
                "returnUrl": return_url,
                "trialDays": 0,  # No trial on plan change
                "test": False,  # TODO: from SHOPIFY_BILLING_TEST setting
                "lineItems": [line_item],
                "replacementBehavior": replacement_behavior,
            },
        )

        create_data = data.get("appSubscriptionCreate", {})
        user_errors = create_data.get("userErrors", [])
        if user_errors:
            error_msg = user_errors[0].get("message", "Unknown error")
            logger.warning("Plan change failed for %s: %s", shop.domain, error_msg)
            return False, error_msg, {}

        confirmation_url = create_data.get("confirmationUrl", "")

        # Update local subscription (status will be updated via webhook after approval)
        subscription.plan = new_plan
        subscription.save(update_fields=["plan", "updated_at"])

        logger.info(
            "Plan change %s→%s for %s (behavior=%s)",
            current_plan,
            new_plan,
            shop.domain,
            replacement_behavior,
        )
        return (
            True,
            "Plan change initiated",
            {
                "confirmation_url": confirmation_url,
                "replacement_behavior": replacement_behavior,
                "is_upgrade": upgrade,
                "plan": new_plan,
                "interval": interval,
            },
        )

    finally:
        client.close()
