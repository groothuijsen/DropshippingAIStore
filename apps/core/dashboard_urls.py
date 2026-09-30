"""Dashboard URLs — placeholder for T-003."""

from django.urls import path

from .views import health_check

urlpatterns = [
    path("dashboard/", health_check, name="dashboard"),
]
