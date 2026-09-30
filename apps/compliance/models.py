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


class WithdrawalRequestStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    HANDLED = "handled", "Handled"


class WithdrawalRequest(models.Model):
    """A withdrawal request submitted via the app proxy (07 §8).

    The only table containing personal data of shoppers (AGENTS.md §2).
    Retention: 2 years (beat task deletes afterwards).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="withdrawal_requests")
    reference = models.CharField(
        max_length=20,
        unique=True,
        help_text="e.g. MQW-7F3K9Q — shown to the customer",
    )
    customer_name = models.CharField(max_length=200)
    order_identifier = models.CharField(
        max_length=100,
        help_text="Order number as entered (not validated against Shopify)",
    )
    email = models.EmailField()
    locale = models.CharField(max_length=5, default="en")
    submitted_at = models.DateTimeField()
    confirmation_sent_at = models.DateTimeField(null=True, blank=True)
    merchant_notified_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=WithdrawalRequestStatus.choices,
        default=WithdrawalRequestStatus.SUBMITTED,
    )

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.reference} — {self.customer_name} ({self.status})"
