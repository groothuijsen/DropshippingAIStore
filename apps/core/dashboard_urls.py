"""Dashboard URLs."""

from django.urls import path

from apps.compliance.views import delivery_override, delivery_profiles

from .views import business_details, dashboard, store_settings

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("settings/store/", store_settings, name="store_settings"),
    path("settings/business/", business_details, name="business_details"),
    path("settings/delivery/", delivery_profiles, name="delivery_profiles"),
    path(
        "products/<path:product_gid>/delivery/",
        delivery_override,
        name="delivery_override",
    ),
]
