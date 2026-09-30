"""Admin for themes."""

from django.contrib import admin

from .models import BrandKit


@admin.register(BrandKit)
class BrandKitAdmin(admin.ModelAdmin):
    list_display = ("shop", "brand_name", "tone", "style_preset", "tokens_synced_at")
    list_filter = ("tone", "style_preset")
    search_fields = ("shop__domain", "brand_name")
    readonly_fields = ("tokens_synced_at", "created_at", "updated_at")
