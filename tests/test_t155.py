from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.test import Client

from apps.marketing.models import Lead

pytestmark = pytest.mark.django_db
M = {"HTTP_HOST": "shopify.mosaiq.marketing"}


@pytest.fixture(autouse=True)
def _hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]
    settings.RESEND_API_KEY = "test-key"
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


def _post(**kw):
    data = {"email": "lead@example.com", "shop_domain": "x.myshopify.com", "lang": "en", "consent": "on", "website": ""}
    data.update(kw)
    return Client().post("/early-access/", data, **M)


class TestEarlyAccessForm:
    def test_get_renders_form(self):
        html = Client().get("/early-access/", **M).content.decode()
        assert "early-access-form" in html and "csrfmiddlewaretoken" in html

    @patch('apps.marketing.views.send_email', return_value=True)
    def test_valid_post_creates_lead_and_sends_confirm(self, mock_send):
        resp = _post()
        assert resp.status_code == 200 and b"Check your inbox" in resp.content
        lead = Lead.objects.get(email='lead@example.com')
        assert lead.confirmed_at is None and len(lead.confirm_token) > 20
        assert mock_send.called

    @patch('apps.marketing.views.send_email', return_value=True)
    def test_honeypot_silently_drops(self, mock_send):
        _post(website='http://spam.example')
        assert not Lead.objects.filter(email='lead@example.com').exists()
        assert not mock_send.called

    def test_consent_required(self):
        resp = _post(consent='')
        assert Lead.objects.count() == 0

    @patch('apps.marketing.views.send_email', return_value=True)
    def test_rate_limit_after_five(self, mock_send):
        for i in range(5):
            Lead.objects.all().delete()
            _post(email=f'l{i}@example.com')
        Lead.objects.all().delete()
        _post(email='sixth@example.com')
        assert not Lead.objects.filter(email='sixth@example.com').exists()


class TestConfirmAndCleanup:
    @patch('apps.marketing.views.send_email', return_value=True)
    def test_confirm_sets_confirmed_at(self, mock_send):
        lead = Lead.objects.create(email='c@example.com', confirm_token='tok123', lang='en')
        resp = Client().get("/early-access/confirm/?token=tok123", **M)
        assert b"Confirmed" in resp.content
        lead.refresh_from_db()
        assert lead.confirmed_at is not None

    def test_cleanup_removes_old_unconfirmed(self):
        old = Lead.objects.create(email='old@example.com', confirm_token='t1')
        Lead.objects.filter(pk=old.pk).update(created_at=datetime.now(UTC) - timedelta(days=8))
        Lead.objects.create(email='new@example.com', confirm_token='t2')
        from django.core.management import call_command
        call_command('cleanup_leads')
        assert not Lead.objects.filter(email='old@example.com').exists()
        assert Lead.objects.filter(email='new@example.com').exists()


class TestInstallSwitch:
    def test_falls_back_to_early_access_when_not_listed(self, settings):
        settings.MARKETING_APP_LISTED = False
        html = Client().get("/pricing/", **M).content.decode()
        assert "/early-access/" in html

    def test_install_url_when_listed(self, settings):
        settings.MARKETING_APP_LISTED = True
        settings.MARKETING_APP_HANDLE = "mosaiq"
        html = Client().get("/pricing/", **M).content.decode()
        assert "apps.shopify.com/mosaiq/install" in html
