"""Dashboard URLs."""

from django.urls import path

from apps.compliance.views import (
    delivery_override,
    delivery_profiles,
    gpsr_form,
    price_advisor,
    price_apply,
)
from apps.core.onboarding_views import onboarding
from apps.generator.editor_views import apply_edit_view, editor_panel, page_editor, reject_edit_view
from apps.generator.product_start_views import job_status_view, product_start_view
from apps.generator.start_views import start_panel, start_wizard

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
    path("pages/<uuid:page_id>/edit/", page_editor, name="page_editor"),
    path("pages/<uuid:page_id>/edit/panel/", editor_panel, name="page_editor_panel"),
    path("pages/<uuid:page_id>/edit/<uuid:edit_id>/apply/", apply_edit_view, name="page_edit_apply"),
    path("pages/<uuid:page_id>/edit/<uuid:edit_id>/reject/", reject_edit_view, name="page_edit_reject"),
    path(
        "products/<path:product_gid>/gpsr/",
        gpsr_form,
        name="gpsr_form",
    ),
    path("onboarding/", onboarding, name="onboarding"),
    path("onboarding/<str:step>/", onboarding, name="onboarding_step"),
    path("start/", start_wizard, name="start_wizard"),
    path("start/panel/", start_panel, name="start_panel"),
    path("start/product/", product_start_view, name="product_start"),
    path("jobs/<uuid:job_id>/", job_status_view, name="job_status"),
    path(
        "products/<path:product_gid>/pricing/apply/",
        price_apply,
        name="price_advice_apply",
    ),
    path(
        "products/<path:product_gid>/pricing/",
        price_advisor,
        name="price_advisor",
    ),
]
