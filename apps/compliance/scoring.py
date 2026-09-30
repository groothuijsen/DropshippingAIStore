"""Claims scoring — calculates claims_score from findings.

See docs/07-compliance.md §4, §9.
claims_score = 100 − 25 per block − 5 per warn, minimum 0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .claims import Finding


def claims_score(findings: list[Finding]) -> int:
    """Calculate claims_score from findings.

    100 − 25 per block − 5 per warn, minimum 0.
    Only counts findings without override_reason.
    """
    score = 100
    for finding in findings:
        if finding.override_reason:
            continue  # Overridden findings don't count
        if finding.is_block:
            score -= 25
        elif finding.is_warn:
            score -= 5
    return max(0, score)


def page_score(
    findings: list[Finding],
    gpsr_complete: bool = True,
    unit_price_required: bool = True,
    unit_price_complete: bool = True,
) -> int:
    """Calculate Page.compliance_score (07 §9).

    100 − 25 × open_block_count − 5 × open_warn_count (without override)
    − 20 if GPSR incomplete − 10 if unit price missing where required.
    Minimum 0.
    """
    score = 100
    for finding in findings:
        if finding.override_reason:
            continue
        if finding.is_block:
            score -= 25
        elif finding.is_warn:
            score -= 5

    if not gpsr_complete:
        score -= 20

    if unit_price_required and not unit_price_complete:
        score -= 10

    return max(0, score)


def has_open_block(findings: list[Finding]) -> bool:
    """Check if there are any open block findings (publishing gate)."""
    return any(f.is_block and not f.override_reason for f in findings)
