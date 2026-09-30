"""Health check endpoint."""

from django.urls import path

from .views import health_check

app_name = "core_health"

urlpatterns = [
    path("", health_check, name="healthz"),
]
