"""Onboarding flow — state machine for the merchant onboarding.

See docs/09-ui-screens.md, docs/specs/F05-brandkit.md criterion 1.
Steps: language → brand → sources → theme → withdrawal → done.
Back button works; stopping halfway resumes at last step.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.core.models import Shop

logger = logging.getLogger(__name__)

ONBOARDING_STEPS = ["language", "brand", "sources", "theme", "withdrawal", "done"]

STEP_ORDER: dict[str, int] = {step: idx for idx, step in enumerate(ONBOARDING_STEPS)}


def get_current_step(shop: Shop) -> str:
    """Get the current onboarding step for a shop."""
    return shop.onboarding_step or "language"


def get_next_step(current: str) -> str | None:
    """Get the next step after the current one. Returns None if done."""
    idx = STEP_ORDER.get(current)
    if idx is None or idx >= len(ONBOARDING_STEPS) - 1:
        return None
    return ONBOARDING_STEPS[idx + 1]


def get_prev_step(current: str) -> str | None:
    """Get the previous step. Returns None if on the first step."""
    idx = STEP_ORDER.get(current)
    if idx is None or idx <= 0:
        return None
    return ONBOARDING_STEPS[idx - 1]


def set_step(shop: Shop, step: str) -> None:
    """Set the onboarding step for a shop."""
    if step not in STEP_ORDER:
        raise ValueError(f"Invalid onboarding step: {step}")
    shop.onboarding_step = step
    shop.save(update_fields=["onboarding_step"])


def advance(shop: Shop) -> str | None:
    """Advance to the next step. Returns the new step, or None if done."""
    current = get_current_step(shop)
    next_step = get_next_step(current)
    if next_step is None:
        return None
    set_step(shop, next_step)
    return next_step


def go_back(shop: Shop) -> str | None:
    """Go back one step. Returns the new step, or None if on first step."""
    current = get_current_step(shop)
    prev_step = get_prev_step(current)
    if prev_step is None:
        return None
    set_step(shop, prev_step)
    return prev_step


def is_complete(shop: Shop) -> bool:
    """Check if onboarding is complete."""
    return shop.onboarding_step == "done"


def get_step_data(shop: Shop, step: str) -> dict[str, Any]:
    """Get data needed to render a specific step."""
    data: dict[str, Any] = {"step": step}

    if step == "brand":
        from apps.themes.models import BrandKit

        try:
            bk = BrandKit.objects.get(shop=shop)
            data["brandkit"] = bk
        except BrandKit.DoesNotExist:
            data["brandkit"] = None

        data["presets"] = get_step_names()
        data["tones"] = ["warm", "premium", "playful", "clinical", "sporty"]

    elif step == "sources":
        data["import_apps"] = shop.import_apps or []
        data["available_apps"] = ["dsers", "cj", "zendrop", "autods", "printify", "printful", "other", "none"]

    elif step == "theme":
        from apps.core.deep_links import BLOCK_TARGETS, EMBED_TARGETS

        data["blocks"] = BLOCK_TARGETS
        data["embeds"] = EMBED_TARGETS

    elif step == "language":
        data["current_locale"] = shop.ui_locale or "en"
        data["available_locales"] = ["nl", "en", "de"]

    return data


def get_step_names() -> list[str]:
    """Get preset names."""
    from apps.themes.presets import get_preset_names

    return get_preset_names()
