"""Dashboard URLs."""

from django.urls import path

from .views import business_details, dashboard, store_settings

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("settings/store/", store_settings, name="store_settings"),
    path("settings/business/", business_details, name="business_details"),
]
