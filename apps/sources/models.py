"""Models for sources — ProductSource.

See docs/02-data-model.md §sources.
"""

import uuid

from django.db import models


class SourceApp(models.TextChoices):
    MANUAL = "manual", "Manual"
    DSERS = "dsers", "DSers"
    CJ = "cj", "CJ Dropshipping"
    ZENDROP = "zendrop", "Zendrop"
    AUTODS = "autods", "AutoDS"
    PRINTIFY = "printify", "Printify"
    PRINTFUL = "printful", "Printful"
    UNKNOWN_APP = "unknown_app", "Unknown app"


class DetectedBy(models.TextChoices):
    MOSAIQ = "mosaiq", "Created by Mosaiq"
    FULFILLMENT_LOCATION = "fulfillment_location", "Fulfillment location"
    ONBOARDING = "onboarding", "Onboarding answer"
    VENDOR = "vendor", "Vendor field"
    SKU = "sku", "SKU pattern"
    MERCHANT = "merchant", "Merchant confirmed"


class ProductSource(models.Model):
    """Tracks where a product came from and which fields Mosaiq may write."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="product_sources")
    product_gid = models.CharField(max_length=255)
    source = models.CharField(max_length=20, choices=SourceApp.choices)
    detected_by = models.CharField(max_length=40, choices=DetectedBy.choices)
    created_by_mosaiq = models.BooleanField(
        default=False,
        help_text="Only True after product_create_manual; sole condition for full write access",
    )
    locked_fields = models.JSONField(
        default=list,
        help_text="List of field names Mosaiq never writes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "product_gid"],
                name="unique_product_source_per_shop",
            ),
        ]
        indexes = [
            models.Index(fields=["shop", "product_gid"]),
        ]

    def __str__(self) -> str:
        return f"{self.product_gid} — {self.source} ({self.detected_by})"
