"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

from apps.core.views import oauth_callback

urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/callback", oauth_callback, name="oauth_callback"),
    path("healthz/", include("apps.core.urls")),
    path("app/", include("apps.core.dashboard_urls")),
    path("app/support/", include("apps.support.urls")),
    path("webhooks/shopify/", include("apps.webhooks.urls")),
    # Marketing site (F19) — host-guarded inside the views: only
    # shopify.mosaiq.marketing serves it; app host root redirects to /app/.
    path("", include("apps.marketing.urls")),
]
