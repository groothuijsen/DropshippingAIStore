"""Core URL configuration."""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.dashboard_urls")),
]
