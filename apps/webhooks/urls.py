"""Webhook URLs."""

from django.urls import path

from .views import shopify_webhook

urlpatterns = [
    path("", shopify_webhook, name="shopify_webhook"),
]
