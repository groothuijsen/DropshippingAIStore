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
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    refresh_token_encrypted = models.BinaryField()
    refresh_token_expires_at = models.DateTimeField(null=True, blank=True)
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
    installation_id = models.CharField(max_length=255, blank=True, default="")

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


class BusinessDetails(models.Model):
    """Merchant business facts (12 §2.1).

    Used by legal templates, the contact page and the shipping/returns
    pages. Mosaiq never invents these facts — missing ones block go-live
    of the pages that need them (D-15.4).
    """

    shop = models.OneToOneField(
        Shop, on_delete=models.CASCADE, related_name="business_details"
    )
    legal_name = models.CharField(max_length=200)
    trade_name = models.CharField(
        max_length=200, blank=True, help_text="Defaults to BrandKit.brand_name"
    )
    street = models.CharField(max_length=200)
    postal_code = models.CharField(max_length=20)
    city = models.CharField(max_length=100)
    country_code = models.CharField(
        max_length=2, help_text="ISO 3166-1 alpha-2, uppercase"
    )
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    company_reg_no = models.CharField(
        max_length=40, blank=True, help_text="KvK / HRB / BCE"
    )
    vat_id = models.CharField(
        max_length=20, blank=True, help_text="Format checked against country prefix only"
    )
    return_address_same = models.BooleanField(default=True)
    return_address = models.JSONField(
        null=True,
        blank=True,
        help_text="Same keys as the address fields when return_address_same is False",
    )
    updated_at = models.DateTimeField(auto_now=True)

    PURPOSE_FIELDS: dict[str, list[str]] = {
        "legal": ["legal_name", "street", "postal_code", "city", "country_code", "email"],
        "contact": ["legal_name", "email"],
        "impressum": [
            "legal_name",
            "street",
            "postal_code",
            "city",
            "country_code",
            "email",
            "company_reg_no",
        ],
        "returns": ["legal_name", "street", "postal_code", "city", "country_code"],
    }

    def clean(self) -> None:
        """VAT ID format check per country prefix only (12 §2.1)."""
        super().clean()
        if (
            self.vat_id
            and self.country_code
            and not self.vat_id.upper().startswith(self.country_code.upper())
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError(
                {"vat_id": f"Must start with the country prefix ({self.country_code})."}
            )

    def is_complete(self, purpose: str) -> list[str]:
        """Return the list of missing fields for a purpose.

        Purposes: legal, contact, impressum, returns.
        """
        fields = self.PURPOSE_FIELDS.get(purpose)
        if fields is None:
            raise ValueError(f"Unknown purpose: {purpose!r}")
        missing = [f for f in fields if not getattr(self, f)]
        if purpose == "returns" and not self.return_address_same and not self.return_address:
            missing.append("return_address")
        return missing

    def __str__(self) -> str:
        return f"BusinessDetails {self.legal_name} ({self.shop.domain})"


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
