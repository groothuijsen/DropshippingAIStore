"""Webhook receipt model — deduplication for Shopify webhooks."""

from django.db import models


class WebhookReceipt(models.Model):
    """Records each inbound webhook to prevent re-processing."""

    webhook_id = models.CharField(max_length=100, unique=True)
    topic = models.CharField(max_length=80)
    shop_domain = models.CharField(max_length=255)
    received_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)
    body_json = models.JSONField(null=True, blank=True, help_text="Parsed webhook body")

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["webhook_id"], name="ix_webhook_receipt_id"),
            models.Index(fields=["processed", "received_at"], name="ix_webhook_receipt_proc"),
        ]

    def __str__(self) -> str:
        status = "processed" if self.processed else "pending"
        return f"{self.topic} ({self.shop_domain}) [{status}]"
