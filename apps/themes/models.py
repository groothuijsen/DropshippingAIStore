"""Models for themes — BrandKit.

See docs/02-data-model.md §themes.
"""

import uuid

from django.db import models


class Tone(models.TextChoices):
    WARM = "warm", "Warm"
    PREMIUM = "premium", "Premium"
    PLAYFUL = "playful", "Playful"
    CLINICAL = "clinical", "Clinical"
    SPORTY = "sporty", "Sporty"


class StylePreset(models.TextChoices):
    CLEAN = "clean", "Clean"
    BOLD = "bold", "Bold"
    ORGANIC = "organic", "Organic"
    LUXE = "luxe", "Luxe"
    TECH = "tech", "Tech"
    SOFT = "soft", "Soft"


class BrandKit(models.Model):
    """Brand configuration for a shop — palette, fonts, style preset."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.OneToOneField("core.Shop", on_delete=models.CASCADE, related_name="brandkit")
    brand_name = models.CharField(max_length=80)
    tone = models.CharField(max_length=20, choices=Tone.choices)
    palette = models.JSONField(
        help_text='{"primary":"#RRGGBB","secondary":...,"accent":...,"background":...,"text":...}'
    )
    font_heading = models.CharField(
        max_length=40,
        blank=True,
        help_text="Key from bundled font list; empty = inherit theme font",
    )
    font_body = models.CharField(
        max_length=40,
        blank=True,
        help_text="Key from bundled font list; empty = inherit theme font",
    )
    style_preset = models.CharField(max_length=20, choices=StylePreset.choices)
    tagline = models.CharField(
        max_length=60,
        blank=True,
        help_text="Brand tagline from the niche_brand proposal (F15-5)",
    )
    logo_file_gid = models.CharField(max_length=255, null=True, blank=True)
    tokens_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last metafieldsSet of the design tokens",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.brand_name} ({self.style_preset})"
