"""SavedTemplate model — save and reuse page templates.

See docs/02-data-model.md (SavedTemplate), docs/specs/F08-templates.md.
structure contains: page_type, section order, per section type + display settings.
NO product text, prices, images or claims.
"""

import uuid

from django.db import models

from apps.core.models import Shop
from apps.generator.models import PageType


class SavedTemplate(models.Model):
    """A saved page template — structure only, no product-specific content."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_shop = models.ForeignKey(
        Shop,
        on_delete=models.CASCADE,
        related_name="saved_templates",
    )
    name = models.CharField(max_length=120)
    page_type = models.CharField(
        max_length=20,
        choices=PageType.choices,
        default=PageType.PDP,
    )
    structure = models.JSONField(
        default=dict,
        help_text="Section order + display settings; NO product text/prices/images/claims",
    )
    shared_with_account = models.BooleanField(
        default=False,
        help_text="Available to other shops of the same Shopify organization (v1.2; MVP: own shop only)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.page_type})"

    @property
    def section_order(self) -> list[str]:
        """Get section order from structure."""
        return self.structure.get("section_order", [])

    @property
    def section_settings(self) -> dict[str, dict]:
        """Get per-section display settings from structure."""
        return self.structure.get("section_settings", {})
