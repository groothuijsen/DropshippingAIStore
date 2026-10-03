"""Marketing analytics - cookieless, first-party (T-154)."""

from django.db import models


class MarketingHit(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    path = models.CharField(max_length=300)
    referrer_host = models.CharField(max_length=200, blank=True, default="")
    lang = models.CharField(max_length=5, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["path", "created_at"])]


class Lead(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    email = models.EmailField(unique=True)
    shop_domain = models.CharField(max_length=200, blank=True, default='')
    lang = models.CharField(max_length=5, default='en')
    consent_text = models.TextField(blank=True, default='')
    confirm_token = models.CharField(max_length=64, unique=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    @property
    def has_confirmed(self) -> bool:
        return self.confirmed_at is not None

    @property
    def days_since_confirmed(self) -> int | None:
        from django.utils import timezone
        if self.confirmed_at is None:
            return None
        return (timezone.now() - self.confirmed_at).days


class OnboardingEmail(models.Model):
    """Tracks sent onboarding emails to prevent duplicate cron sends."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='onboarding_emails')
    step = models.CharField(max_length=20)  # welcome / start / compliance
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('lead', 'step')]


class UninstallFeedback(models.Model):
    """Why did a merchant uninstall? (T-159 uninstall-reason-link)."""

    REASONS = [
        ('too_expensive', 'Too expensive'),
        ('not_useful', 'Not useful / missing features'),
        ('too_complex', 'Too complex'),
        ('switched', 'Switched to another tool'),
        ('closed_shop', 'Closed the shop'),
        ('other', 'Other'),
    ]
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    email = models.EmailField(blank=True, default='')
    shop_domain = models.CharField(max_length=200, blank=True, default='')
    reason = models.CharField(max_length=30, choices=REASONS)
    comment = models.TextField(blank=True, default='')
    lang = models.CharField(max_length=5, default='en')

    def __str__(self) -> str:
        return f'{self.reason} ({self.email or self.shop_domain or "anon"})'
