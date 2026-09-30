"""Core models — Shop, AuditLog."""

import uuid

from django.db import models


class ShopStatus(models.TextChoices):
    ACTIVE = "active"
    UNINSTALLED = "uninstalled"
    FROZEN = "frozen"


class OnboardingStep(models.TextChoices):
    LANGUAGE = "language"
    BRAND = "brand"
    SOURCES = "sources"
    THEME = "theme"
    WITHDRAWAL = "withdrawal"
    DONE = "done"


class Shop(models.Model):
    """Shopify shop — one per installed store."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=255, unique=True, help_text="*.myshopify.com, lowercase")
    shopify_gid = models.CharField(max_length=255, unique=True)

    # Token storage (encrypted with Fernet)
    access_token_encrypted = models.BinaryField()
    access_token_expires_at = models.DateTimeField()
    refresh_token_encrypted = models.BinaryField()
    refresh_token_expires_at = models.DateTimeField()
    needs_reauth = models.BooleanField(default=False)

    scopes = models.CharField(max_length=1000, blank=True)
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    primary_locale = models.CharField(max_length=10, default="en")
    iana_timezone = models.CharField(max_length=64, default="UTC")
    currency_code = models.CharField(max_length=3, default="USD")
    country_code = models.CharField(max_length=2, blank=True)
    ui_locale = models.CharField(max_length=5, default="en")

    status = models.CharField(
        max_length=20,
        choices=ShopStatus.choices,
        default=ShopStatus.ACTIVE,
    )
    installed_at = models.DateTimeField(auto_now_add=True)
    uninstalled_at = models.DateTimeField(null=True, blank=True)

    # Onboarding
    mosaiq_templates_ready = models.BooleanField(default=False)
    onboarding_step = models.CharField(
        max_length=40,
        choices=OnboardingStep.choices,
        default=OnboardingStep.LANGUAGE,
    )
    import_apps = models.JSONField(default=list, blank=True)
    ship_cutoff = models.JSONField(null=True, blank=True)
    guarantee_policy = models.TextField(blank=True)
    stock_threshold = models.PositiveSmallIntegerField(default=5)
    ai_label_default = models.BooleanField(default=True)

    class Meta:
        ordering = ["-installed_at"]

    def __str__(self) -> str:
        return f"{self.domain} ({self.status})"


class AuditLog(models.Model):
    """Audit trail for sensitive actions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="audit_logs")
    actor = models.CharField(max_length=20, help_text="merchant, system, support")
    action = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.actor}:{self.action} @ {self.shop.domain}"
