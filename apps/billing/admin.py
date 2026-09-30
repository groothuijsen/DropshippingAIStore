"""Admin for billing."""

from django.contrib import admin

from .models import Subscription, TrialLedger, UsageCounter


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("shop", "plan", "interval", "status", "trial_ends_at", "current_period_end", "test")
    list_filter = ("plan", "status", "interval", "test")
    search_fields = ("shop__domain",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(UsageCounter)
class UsageCounterAdmin(admin.ModelAdmin):
    list_display = (
        "shop",
        "period_start",
        "store_generations",
        "ai_images",
        "reserved_store_generations",
        "reserved_ai_images",
    )
    list_filter = ("period_start",)
    search_fields = ("shop__domain",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(TrialLedger)
class TrialLedgerAdmin(admin.ModelAdmin):
    list_display = ("domain_sha256", "first_trial_at")
    search_fields = ("domain_sha256",)
    readonly_fields = ("created_at",)
