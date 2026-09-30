"""Admin for sources."""

from django.contrib import admin

from .models import ProductSource


@admin.register(ProductSource)
class ProductSourceAdmin(admin.ModelAdmin):
    list_display = ("shop", "product_gid", "source", "detected_by", "created_by_mosaiq", "created_at")
    list_filter = ("source", "detected_by", "created_by_mosaiq")
    search_fields = ("shop__domain", "product_gid")
    readonly_fields = ("created_at", "updated_at")
