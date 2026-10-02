"""Models for compliance — PriceHistory, PriceAttestation, etc.

See docs/02-data-model.md, docs/07-compliance.md.
"""

import json
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
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


class DeliveryProfile(models.Model):
    """Delivery estimate per source app (12 §2.4).

    One row per (shop, source_app). transit_days and shipping_cost are
    per-market JSON: {"NL": [5, 9]} and {"NL": {"amount": "4.95",
    "free_from": "40.00"}}.
    """

    SOURCE_APPS = (
        ("dsers", "DSers"),
        ("cj", "CJ Dropshipping"),
        ("zendrop", "Zendrop"),
        ("autods", "AutoDS"),
        ("printify", "Printify"),
        ("printful", "Printful"),
        ("manual", "Manual"),
        ("other", "Other"),
    )

    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="delivery_profiles")
    source_app = models.CharField(max_length=20, choices=SOURCE_APPS)
    ship_from_country = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2")
    processing_days_min = models.PositiveSmallIntegerField()
    processing_days_max = models.PositiveSmallIntegerField()
    transit_days = models.JSONField(
        help_text='Per market: {"NL": [5, 9], "DE": [6, 10]}; each [min, max]'
    )
    shipping_cost = models.JSONField(
        null=True,
        blank=True,
        help_text='Per market: {"NL": {"amount": "4.95", "free_from": "40.00"}}',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "source_app"],
                name="unique_delivery_profile_per_shop_source",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.processing_days_max > 15:
            errors["processing_days_max"] = "Max 15 working days."
        if self.processing_days_min > self.processing_days_max:
            errors["processing_days_min"] = "Min must be <= max."
        if isinstance(self.transit_days, dict):
            for market, rng in self.transit_days.items():
                if not (isinstance(rng, list) and len(rng) == 2 and rng[0] <= rng[1]):
                    errors["transit_days"] = (
                        f"Market {market}: each entry must be [min, max] with min <= max."
                    )
                    break
        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"DeliveryProfile {self.source_app} ({self.ship_from_country}) @ {self.shop.domain}"


class DeliveryOverride(models.Model):
    """Per-product delivery override (12 §2.4). Null fields fall back to the profile."""

    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="delivery_overrides")
    product_gid = models.CharField(max_length=255)
    ship_from_country = models.CharField(max_length=2, blank=True, null=True)
    processing_days_min = models.PositiveSmallIntegerField(null=True, blank=True)
    processing_days_max = models.PositiveSmallIntegerField(null=True, blank=True)
    transit_days = models.JSONField(null=True, blank=True)
    shipping_cost = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "product_gid"],
                name="unique_delivery_override_per_shop_product",
            ),
        ]

    def __str__(self) -> str:
        return f"DeliveryOverride {self.product_gid} @ {self.shop.domain}"

    @property
    def transit_days_json(self) -> str:
        return json.dumps(self.transit_days) if self.transit_days else ""

    @property
    def shipping_cost_json(self) -> str:
        return json.dumps(self.shipping_cost) if self.shipping_cost else ""


def _default_markets() -> list[str]:
    """Default markets for PricingSettings (Django can't serialize lambdas)."""
    return ["NL"]


class PricingSettings(models.Model):
    """Price advisor defaults per shop (F17-2, 12 §2.6)."""

    shop = models.OneToOneField("core.Shop", on_delete=models.CASCADE, related_name="pricing_settings")
    payment_fee_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.029"))
    payment_fee_fixed = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.30"))
    returns_allowance_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.05"))
    target_margin_pct = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.30"))
    price_ending = models.CharField(
        max_length=2,
        choices=[("95", ".95"), ("99", ".99"), ("00", ".00")],
        default="95",
    )
    markets = models.JSONField(default=_default_markets, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.returns_allowance_pct + self.target_margin_pct >= Decimal("0.90"):
            raise ValidationError("Returns allowance + target margin must sum to less than 0.90.")
        if self.price_ending not in ("95", "99", "00"):
            raise ValidationError("Price ending must be 95, 99 or 00.")

    def __str__(self):
        return f"PricingSettings @ {self.shop.domain}"

    @property
    def payment_fee_pct_display(self) -> str:
        return str(self.payment_fee_pct * 100)

    @property
    def returns_allowance_pct_display(self) -> str:
        return str(self.returns_allowance_pct * 100)

    @property
    def target_margin_pct_display(self) -> str:
        return str(self.target_margin_pct * 100)


class PriceAdvice(models.Model):
    """One price-advisor calculation, optionally applied (F17-4)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="price_advices")
    product_gid = models.CharField(max_length=255)
    market = models.CharField(max_length=80)
    inputs = models.JSONField(default=dict)
    advice = models.JSONField(default=dict)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["shop", "product_gid"])]

    def __str__(self):
        return f"PriceAdvice {self.product_gid} {self.market} applied={self.applied_at is not None}"
