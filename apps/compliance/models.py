"""Models for compliance — PriceHistory, PriceAttestation, etc.

See docs/02-data-model.md, docs/07-compliance.md.
"""

import uuid

from django.db import models


class PriceHistory(models.Model):
    """Price observation for Omnibus compliance (07 §1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="price_history")
    variant_gid = models.CharField(max_length=255)
    market_handle = models.CharField(max_length=80, default="primary")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    observed_at = models.DateTimeField()
    source = models.CharField(
        max_length=20,
        choices=[
            ("install_snapshot", "Install snapshot"),
            ("webhook", "Webhook"),
            ("daily_snapshot", "Daily snapshot"),
            ("merchant_attested", "Merchant attested"),
        ],
    )

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["shop", "variant_gid", "market_handle", "observed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.variant_gid} @ {self.price} {self.currency} ({self.source})"


class PriceAttestation(models.Model):
    """Merchant-attested lowest price for the 30-day window (07 §1.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="price_attestations")
    variant_gid = models.CharField(max_length=255)
    lowest_price_30d = models.DecimalField(max_digits=12, decimal_places=2)
    valid_until = models.DateTimeField()

    class Meta:
        ordering = ["-valid_until"]

    def __str__(self) -> str:
        return f"{self.variant_gid} attested {self.lowest_price_30d}"
