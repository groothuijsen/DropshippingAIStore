"""Core admin."""

from django.contrib import admin

from .models import AuditLog, Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("domain", "name", "status", "installed_at", "needs_reauth")
    list_filter = ("status", "needs_reauth")
    search_fields = ("domain", "name")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("actor", "action", "shop", "created_at")
    list_filter = ("actor",)
    search_fields = ("action",)
    raw_id_fields = ("shop",)
