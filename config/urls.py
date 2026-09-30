"""URL configuration for mosaiq project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", include("apps.core.health")),
    path("app/", include("apps.core.urls")),
    path("webhooks/shopify/", include("apps.webhooks.urls")),
    path("proxy/", include("apps.compliance.proxy_urls")),
]
