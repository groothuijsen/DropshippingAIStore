"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

from apps.core.salespage import salespage

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", include("apps.core.urls")),
    path("app/", include("apps.core.dashboard_urls")),
    path("app/support/", include("apps.support.urls")),
    path("webhooks/shopify/", include("apps.webhooks.urls")),
    # Public Shopify app salespage — host-guarded (shopify.mosaiq.marketing only).
    path("", salespage),
]
