"""Offer model — volume, BOGO, free gift offers.

See docs/02-data-model.md (Offer), docs/07-compliance.md §3 (timer rules),
docs/specs/F09-bundles.md.
"""

from django.db import models

from apps.core.models import Shop


class OfferStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ENDED = "ended", "Ended"


class OfferKind(models.TextChoices):
    VOLUME = "volume", "Volume"
    BOGO = "bogo", "BOGO"
    FREE_GIFT = "free_gift", "Free gift"


class Offer(models.Model):
    """An offer (volume/BOGO/free gift) attached to a product."""

    shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name="offers",
    )
    product_gid = models.CharField(
        max_length=255,
        help_text="Shopify product GID",
    )
    title = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=20,
        choices=OfferKind.choices,
        default=OfferKind.VOLUME,
    )
    config = models.JSONField(
        default=dict,
        help_text="OfferConfig validated against apps.offers.schemas.OfferConfig",
    )
    status = models.CharField(
        max_length=20,
        choices=OfferStatus.choices,
        default=OfferStatus.DRAFT,
    )
    ends_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="End time for countdown timer; None = no timer",
    )
    show_timer = models.BooleanField(
        default=False,
        help_text="Show countdown timer in storefront",
    )
    # Shopify GIDs after activation
    discount_gid = models.CharField(max_length=255, blank=True, default="")
    offer_display_metaobject_gid = models.CharField(max_length=255, blank=True, default="")
    product_metafield_gid = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Timer rule (07 §3): show_timer=True requires ends_at (02)
            models.CheckConstraint(
                condition=(models.Q(show_timer=False) | models.Q(ends_at__isnull=False)),
                name="offer_timer_requires_ends_at",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.kind}, {self.status})"

    def clean(self) -> None:
        """Validate timer rules (07 §3, F09 criterion 5)."""
        from django.core.exceptions import ValidationError

        # show_timer=True requires ends_at
        if self.show_timer and not self.ends_at:
            raise ValidationError({"show_timer": "Cannot enable timer without an end time (ends_at)."})

        # ends_at cannot be more than 90 days in the future (prevent fake "ending soon")
        if self.ends_at:
            from django.utils import timezone

            max_future = timezone.now() + timezone.timedelta(days=90)
            if self.ends_at > max_future:
                raise ValidationError({"ends_at": "End time cannot be more than 90 days in the future."})

    @property
    def timer_active(self) -> bool:
        """Whether the countdown timer should render (07 §3).

        True only if show_timer=True AND ends_at is set AND in the future.
        """
        from django.utils import timezone

        if not self.show_timer or not self.ends_at:
            return False
        return self.ends_at > timezone.now()

    @property
    def is_expired(self) -> bool:
        """Whether the offer has ended."""
        if not self.ends_at:
            return False
        from django.utils import timezone

        return self.ends_at <= timezone.now()
