"""Webhooks admin."""

from django.contrib import admin

from .models import WebhookReceipt


@admin.register(WebhookReceipt)
class WebhookReceiptAdmin(admin.ModelAdmin):
    list_display = ("webhook_id", "topic", "shop_domain", "processed", "received_at")
    list_filter = ("processed", "topic")
    search_fields = ("webhook_id", "shop_domain")
    readonly_fields = ("received_at",)
