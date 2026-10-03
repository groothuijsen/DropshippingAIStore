"""Models for billing — Subscription, UsageCounter, TrialLedger.

See docs/02-data-model.md §billing, docs/08-billing.md.
"""

import uuid

from django.db import models


class Plan(models.TextChoices):
    STARTER = "starter", "Starter"
    PRO = "pro", "Pro"
    AGENCY = "agency", "Agency"


class Interval(models.TextChoices):
    EVERY_30_DAYS = "every_30_days", "Every 30 days"
    ANNUAL = "annual", "Annual"


class SubscriptionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    CANCELLED = "cancelled", "Cancelled"
    DECLINED = "declined", "Declined"
    EXPIRED = "expired", "Expired"
    FROZEN = "frozen", "Frozen"


class Subscription(models.Model):
    """Shopify app subscription — mirrors Shopify AppSubscriptionStatus."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.OneToOneField("core.Shop", on_delete=models.CASCADE, related_name="subscription")
    plan = models.CharField(max_length=20, choices=Plan.choices)
    interval = models.CharField(max_length=20, choices=Interval.choices, default=Interval.EVERY_30_DAYS)
    shopify_subscription_gid = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.PENDING,
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    test = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.shop.domain} — {self.plan} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status == SubscriptionStatus.ACTIVE


class UsageCounter(models.Model):
    """Per-period usage counters with reservation support.

    Increment only via F() expressions inside a transaction with select_for_update.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="usage_counters")
    period_start = models.DateField(help_text="Start of the 30-day period")
    store_generations = models.PositiveIntegerField(default=0)
    ai_images = models.PositiveIntegerField(default=0)
    page_edits = models.PositiveIntegerField(default=0)
    reserved_store_generations = models.PositiveIntegerField(
        default=0,
        help_text="Reserved at job start, released on completion/failure",
    )
    reserved_ai_images = models.PositiveIntegerField(
        default=0,
        help_text="Reserved at job start, released on completion/failure",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "period_start"],
                name="unique_usage_counter_per_shop_period",
            ),
        ]
        indexes = [
            models.Index(fields=["shop", "period_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.shop.domain} — {self.period_start}"


class TrialLedger(models.Model):
    """Tracks which domains have had a trial.

    No FK to Shop — persists after shop/redact (08 §4).
    Contains only a hash of the shop domain, no personal data.
    """

    domain_sha256 = models.CharField(
        max_length=64,
        unique=True,
        help_text="sha256 of the lowercase shop domain",
    )
    first_trial_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-first_trial_at"]

    def __str__(self) -> str:
        return f"Trial: {self.domain_sha256[:16]}..."


class FoundingDiscount(models.Model):
    """Founding-member discount (T-160 / S13).

    Granted to early merchants at sign-up. Applies for 12 months from
    created_at. The discount percentage is stored per-shop so it can be
    audited and adjusted. When valid_until passes, the full price resumes
    automatically — no manual cancellation needed.
    """

    shop = models.OneToOneField("core.Shop", on_delete=models.CASCADE, related_name="founding_discount")
    percent_off = models.PositiveSmallIntegerField(default=50, help_text="e.g. 50 = 50% off")
    valid_until = models.DateTimeField(help_text="Discount expires automatically after this date")
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Founding {self.percent_off}% off — {self.shop.domain}"

    @property
    def is_active(self) -> bool:
        from django.utils import timezone
        return timezone.now() < self.valid_until
