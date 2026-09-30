"""Plan data — limits and prices stored as data, not scattered.

See docs/08-billing.md §1, docs/00-decisions.md.
"""

from decimal import Decimal
from typing import Any

# ── Limits per plan (08 §1) ───────────────────────────────────────────────

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "starter": {
        "store_generations": 3,
        "live_pages": 15,
        "ai_images": 30,
        "active_offers": 20,
        "ab_test": False,
        "analytics": False,
        "shared_templates": False,
    },
    "pro": {
        "store_generations": 15,
        "live_pages": 60,
        "ai_images": 150,
        "active_offers": 20,
        "ab_test": True,
        "analytics": True,
        "shared_templates": False,
    },
    "agency": {
        "store_generations": 50,
        "live_pages": None,  # unlimited
        "ai_images": 500,
        "active_offers": 20,  # technical limit
        "ab_test": True,
        "analytics": True,
        "shared_templates": True,
    },
}

# ── Prices (00-decisions §pricing) ────────────────────────────────────────

PLAN_PRICES: dict[str, dict[str, Decimal]] = {
    "starter": {
        "every_30_days": Decimal("29.00"),
        "annual": Decimal("290.00"),
    },
    "pro": {
        "every_30_days": Decimal("79.00"),
        "annual": Decimal("790.00"),
    },
    "agency": {
        "every_30_days": Decimal("199.00"),
        "annual": Decimal("1990.00"),
    },
}

TRIAL_DAYS = 7

PLAN_NAMES: dict[str, str] = {
    "starter": "Mosaiq Starter",
    "pro": "Mosaiq Pro",
    "agency": "Mosaiq Agency",
}


def get_plan_limits(plan: str) -> dict[str, Any]:
    """Get limits for a plan. Defaults to starter for unknown plans."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["starter"])


def get_plan_price(plan: str, interval: str) -> Decimal:
    """Get price for a plan+interval. Defaults to starter monthly."""
    prices = PLAN_PRICES.get(plan, PLAN_PRICES["starter"])
    return prices.get(interval, prices["every_30_days"])


def get_plan_name(plan: str, interval: str = "every_30_days") -> str:
    """Get display name for a plan+interval."""
    name = PLAN_NAMES.get(plan, PLAN_NAMES["starter"])
    if interval == "annual":
        name += " (annual)"
    return name


def is_upgrade(old_plan: str, new_plan: str) -> bool:
    """Check if new_plan is an upgrade from old_plan."""
    order = ["starter", "pro", "agency"]
    try:
        return order.index(new_plan) > order.index(old_plan)
    except ValueError:
        return False


def get_replacement_behavior(old_plan: str, new_plan: str) -> str:
    """Get replacementBehavior for upgrade/downgrade (08 §2)."""
    if is_upgrade(old_plan, new_plan):
        return "APPLY_IMMEDIATELY"
    return "APPLY_ON_NEXT_BILLING_CYCLE"
