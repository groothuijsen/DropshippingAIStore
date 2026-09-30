"""Limits — reservation system for usage limits.

See docs/08-billing.md §1, docs/05-ai-pipeline.md §5.
Reserve at job start, convert to consumption on success, release on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import F

if TYPE_CHECKING:
    from apps.core.models import Shop

from .models import UsageCounter
from .plans import get_plan_limits

logger = logging.getLogger(__name__)


@dataclass
class LimitResult:
    """Result of a limit check."""

    allowed: bool
    remaining: int
    limit: int | None  # None = unlimited
    message: str = ""


def _get_plan(shop: Shop) -> str:
    """Get the current plan for a shop. Defaults to starter."""
    from .models import Subscription

    try:
        sub = Subscription.objects.get(shop=shop)
        return sub.plan
    except Subscription.DoesNotExist:
        return "starter"


def _get_or_create_counter(shop: Shop, period_start: date) -> UsageCounter:
    """Get or create a UsageCounter for the current period."""
    counter, _created = UsageCounter.objects.get_or_create(
        shop=shop,
        period_start=period_start,
        defaults={
            "store_generations": 0,
            "ai_images": 0,
            "reserved_store_generations": 0,
            "reserved_ai_images": 0,
        },
    )
    return counter


def get_current_period_start() -> date:
    """Get the start date of the current 30-day period."""

    today = date.today()
    # Simple: period starts on the 1st of each month
    # For a more precise system, we'd track per-shop period_start
    return today.replace(day=1)


def reserve(shop: Shop, resource: str, amount: int = 1) -> LimitResult:
    """Reserve usage for a resource. Returns LimitResult.

    Uses select_for_update + F() expressions to prevent concurrent over-limit.
    """
    if resource not in ("store_generations", "ai_images"):
        raise ValueError(f"Unknown resource: {resource}")

    plan = _get_plan(shop)
    limits = get_plan_limits(plan)
    limit = limits.get(resource)

    period_start = get_current_period_start()

    with transaction.atomic():
        counter = _get_or_create_counter(shop, period_start)

        # Lock the row for concurrent access
        counter = UsageCounter.objects.select_for_update().get(pk=counter.pk)

        # Calculate current usage (consumed + reserved)
        consumed = getattr(counter, resource)
        reserved = getattr(counter, f"reserved_{resource}")

        if limit is not None:
            current_total = consumed + reserved
            remaining = limit - current_total

            if remaining < amount:
                return LimitResult(
                    allowed=False,
                    remaining=max(0, remaining),
                    limit=limit,
                    message=f"PLAN_LIMIT_REACHED: {resource} limit reached ({limit})",
                )

        # Reserve the amount
        UsageCounter.objects.filter(pk=counter.pk).update(
            **{f"reserved_{resource}": F(f"reserved_{resource}") + amount}
        )

        remaining_val = None
        if limit is not None:
            remaining_val = limit - (consumed + reserved + amount)

        return LimitResult(
            allowed=True,
            remaining=remaining_val if remaining_val is not None else -1,
            limit=limit,
        )


def release(shop: Shop, resource: str, amount: int = 1) -> None:
    """Release reserved usage (on job failure/cancel)."""
    period_start = get_current_period_start()

    with transaction.atomic():
        counter = _get_or_create_counter(shop, period_start)
        counter = UsageCounter.objects.select_for_update().get(pk=counter.pk)

        reserved_field = f"reserved_{resource}"
        current_reserved = getattr(counter, reserved_field)

        # Don't go below zero
        new_reserved = max(0, current_reserved - amount)

        UsageCounter.objects.filter(pk=counter.pk).update(**{reserved_field: new_reserved})


def consume(shop: Shop, resource: str, amount: int = 1) -> None:
    """Convert reservation to consumption (on job success)."""
    period_start = get_current_period_start()

    with transaction.atomic():
        counter = _get_or_create_counter(shop, period_start)
        counter = UsageCounter.objects.select_for_update().get(pk=counter.pk)

        # Increment consumed
        UsageCounter.objects.filter(pk=counter.pk).update(**{resource: F(resource) + amount})

        # Decrement reserved
        reserved_field = f"reserved_{resource}"
        current_reserved = getattr(counter, reserved_field)
        new_reserved = max(0, current_reserved - amount)
        UsageCounter.objects.filter(pk=counter.pk).update(**{reserved_field: new_reserved})


def check_pages_live(shop: Shop) -> LimitResult:
    """Check live page count against plan limit.

    Live pages are counted live: Page.objects.filter(shop=shop, status="live").count()
    """
    from apps.generator.models import Page

    plan = _get_plan(shop)
    limits = get_plan_limits(plan)
    limit = limits.get("live_pages")

    live_count = Page.objects.filter(shop=shop, status="live").count()

    if limit is None:
        return LimitResult(allowed=True, remaining=-1, limit=None)

    remaining = limit - live_count

    if remaining <= 0:
        return LimitResult(
            allowed=False,
            remaining=0,
            limit=limit,
            message=f"PLAN_LIMIT_REACHED: live pages limit reached ({limit})",
        )

    return LimitResult(allowed=True, remaining=remaining, limit=limit)


def get_usage_summary(shop: Shop) -> dict[str, Any]:
    """Get a summary of current period usage for a shop."""
    plan = _get_plan(shop)
    limits = get_plan_limits(plan)
    period_start = get_current_period_start()

    counter = _get_or_create_counter(shop, period_start)
    live_pages = check_pages_live(shop)

    return {
        "plan": plan,
        "period_start": period_start.isoformat(),
        "limits": limits,
        "usage": {
            "store_generations": {
                "consumed": counter.store_generations,
                "reserved": counter.reserved_store_generations,
                "limit": limits.get("store_generations"),
            },
            "ai_images": {
                "consumed": counter.ai_images,
                "reserved": counter.reserved_ai_images,
                "limit": limits.get("ai_images"),
            },
            "live_pages": {
                "count": live_pages.limit - live_pages.remaining if live_pages.limit else 0,
                "limit": live_pages.limit,
            },
        },
    }
