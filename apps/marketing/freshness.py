"""Comparison freshness rules (F19-11).

A comparison row set older than 90 days shows a re-verification notice;
older than 120 days the comparison is hidden until it is re-checked.
"""

from __future__ import annotations

from datetime import date

REVIEW_AFTER_DAYS = 90
HIDE_AFTER_DAYS = 120


def comparison_state(last_checked: str, today: date | None = None) -> tuple[str, int]:
    """Return (state, age_days): fresh | review | expired."""
    today = today or date.today()
    age = (today - date.fromisoformat(last_checked)).days
    if age >= HIDE_AFTER_DAYS:
        return "expired", age
    if age >= REVIEW_AFTER_DAYS:
        return "review", age
    return "fresh", age


def annotate_comparisons(sections: list, today: date | None = None) -> list:
    """Attach _state/_age_days to every comparison section dict."""
    for section in sections:
        if isinstance(section, dict) and section.get("type") == "comparison":
            state, age = comparison_state(str(section["last_checked"]), today)
            section["comparison_state"] = state
            section["comparison_age_days"] = age
    return sections
