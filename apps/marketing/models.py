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
