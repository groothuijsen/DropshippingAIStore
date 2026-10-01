"""Tests for the public Shopify app salespage (shopify.mosaiq.marketing)."""

import pytest
from django.test import Client, override_settings

pytestmark = pytest.mark.django_db

SALESPAGE_HOST = "shopify.mosaiq.marketing"


class TestSalespage:
    """Host-based routing: salespage only on shopify.mosaiq.marketing."""

    @override_settings(ALLOWED_HOSTS=["shopify.mosaiq.marketing", "testserver"])
    def test_salespage_renders_on_shopify_subdomain(self):
        client = Client()
        response = client.get("/", HTTP_HOST=SALESPAGE_HOST)
        assert response.status_code == 200
        content = response.content.decode()
        assert "Mosaiq" in content
        # Semantic structure
        assert content.count("<h1>") == 1
        assert "<main" in content
        # Meta layer (rule #20)
        assert "<title>" in content
        assert 'name="description"' in content
        assert "og:title" in content
        assert "application/ld+json" in content

    @override_settings(ALLOWED_HOSTS=["shop.mosaiq.marketing", "testserver"])
    def test_root_404s_on_app_subdomain(self):
        """The app backend subdomain must NOT serve the salespage."""
        client = Client()
        response = client.get("/", HTTP_HOST="shop.mosaiq.marketing")
        assert response.status_code == 404

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_root_404s_on_unknown_host(self):
        client = Client()
        response = client.get("/", HTTP_HOST="testserver")
        assert response.status_code == 404

    @override_settings(ALLOWED_HOSTS=["shopify.mosaiq.marketing", "testserver"])
    def test_salespage_has_primary_cta_and_no_fake_proof(self):
        client = Client()
        response = client.get("/", HTTP_HOST=SALESPAGE_HOST)
        content = response.content.decode()
        # One primary CTA pointing at install / early access
        assert "Install on Shopify" in content or "Get early access" in content
        # AGENTS.md: never fabricate reviews/ratings/social proof
        assert "stars" not in content.lower() or "aggregateRating" not in content
        assert "people are viewing" not in content.lower()
