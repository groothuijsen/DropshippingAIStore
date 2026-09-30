"""Dashboard URLs."""

from django.urls import path

from .views import dashboard, store_settings

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("settings/store/", store_settings, name="store_settings"),
]
