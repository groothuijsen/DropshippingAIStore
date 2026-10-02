"""Dashboard URLs."""

from django.urls import path

from apps.compliance.views import delivery_override, delivery_profiles, price_advisor

from .views import business_details, dashboard, settings_index, store_settings

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("settings/", settings_index, name="settings_index"),
    path("settings/store/", store_settings, name="store_settings"),
    path("settings/business/", business_details, name="business_details"),
    path("settings/delivery/", delivery_profiles, name="delivery_profiles"),
    path(
        "products/<path:product_gid>/delivery/",
        delivery_override,
        name="delivery_override",
    ),
    path(
        "products/<path:product_gid>/pricing/",
        price_advisor,
        name="price_advisor",
    ),
]
