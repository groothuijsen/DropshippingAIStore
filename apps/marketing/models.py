"""Marketing analytics - cookieless, first-party (T-154)."""

from django.db import models


class MarketingHit(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    path = models.CharField(max_length=300)
    referrer_host = models.CharField(max_length=200, blank=True, default="")
    lang = models.CharField(max_length=5, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["path", "created_at"])]
