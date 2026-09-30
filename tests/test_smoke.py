"""Smoke test — verify the project scaffold works."""

import json

import pytest
from django.test import RequestFactory

from apps.core.views import health_check


@pytest.mark.django_db
def test_health_check():
    """Health check returns 200."""
    factory = RequestFactory()
    request = factory.get("/healthz/")
    response = health_check(request)
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["status"] == "ok"


def test_settings_loaded():
    """Django settings are loadable."""
    from django.conf import settings

    assert settings.ROOT_URLCONF == "config.urls"
    assert "apps.core" in settings.INSTALLED_APPS
