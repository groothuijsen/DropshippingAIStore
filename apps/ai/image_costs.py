"""Image cost tracking + budget guard.

See docs/05-ai-pipeline.md §4.4, docs/08-billing.md.
Costs per image (Vertex prices Sept 2026):
- gemini-3.1-flash-image 2K: $0.10
- gemini-3.1-flash-image 1K: $0.067
- gemini-3-pro-image 2K: $0.20 (stronger, ±2× more expensive)
- gpt-image-2.5-sunburst 2K: $0.08
Budget: AI_COST_BUDGET_USD per job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Cost per image (USD) by model + resolution
IMAGE_COSTS: dict[str, dict[str, float]] = {
    "gemini-3.1-flash-image": {
        "2048x2048": 0.10,
        "1024x1024": 0.067,
    },
    "gemini-3-pro-image": {
        "2048x2048": 0.20,
        "1024x1024": 0.133,
    },
    "gpt-image-2.5-sunburst": {
        "2048x2048": 0.08,
        "1024x1024": 0.053,
    },
}

# Budget per job (08 §1)
AI_COST_BUDGET_USD = 2.00


@dataclass
class ImageCostTracker:
    """Tracks image generation costs for a job."""

    budget_usd: float = AI_COST_BUDGET_USD
    spent_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        """Remaining budget."""
        return max(0.0, self.budget_usd - self.spent_usd)

    @property
    def is_exhausted(self) -> bool:
        """Check if budget is exhausted."""
        return self.spent_usd >= self.budget_usd

    def get_cost(self, model: str, resolution: str) -> float:
        """Get cost for a model + resolution."""
        costs = IMAGE_COSTS.get(model, {})
        return costs.get(resolution, 0.0)

    def can_afford(self, model: str, resolution: str) -> bool:
        """Check if we can afford a generation."""
        cost = self.get_cost(model, resolution)
        return cost <= self.remaining_usd

    def record(self, model: str, resolution: str) -> float:
        """Record a generation cost. Returns the cost."""
        cost = self.get_cost(model, resolution)
        self.spent_usd += cost
        logger.info(
            "Image cost: $%.3f for %s @ %s (total: $%.3f / $%.2f)",
            cost,
            model,
            resolution,
            self.spent_usd,
            self.budget_usd,
        )
        return cost

    def reset(self) -> None:
        """Reset the tracker."""
        self.spent_usd = 0.0


def check_budget_remaining(tracker: ImageCostTracker, model: str, resolution: str) -> bool:
    """Check if budget allows one more generation."""
    return tracker.can_afford(model, resolution)
