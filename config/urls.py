"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", include("apps.core.urls")),
    path("app/", include("apps.core.dashboard_urls")),
    path("webhooks/shopify/", include("apps.webhooks.urls")),
]
