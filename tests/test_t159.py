import pytest
from django.test import Client
from django.utils import timezone

from apps.marketing.emails import send_onboarding
from apps.marketing.models import Lead, OnboardingEmail, UninstallFeedback

pytestmark = pytest.mark.django_db
M = {"HTTP_HOST": "shopify.mosaiq.marketing"}


@pytest.fixture(autouse=True)
def _hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]


def _make_lead(email="test@example.com", confirmed=True, lang="en"):
    lead = Lead(
        email=email,
        shop_domain="test.myshopify.com",
        lang=lang,
        confirm_token="tok123",
        confirmed_at=timezone.now() if confirmed else None,
    )
    lead.save()
    return lead


class TestOnboardingEmails:
    def test_day0_welcome_sent(self):
        lead = _make_lead()
        sent = send_onboarding()
        assert sent == 1
        assert OnboardingEmail.objects.filter(lead=lead, step="welcome").exists()

    def test_no_duplicate_sends(self):
        _make_lead()
        send_onboarding()
        sent = send_onboarding()
        assert sent == 0
        assert OnboardingEmail.objects.count() == 1

    def test_unconfirmed_lead_skipped(self):
        _make_lead(confirmed=False)
        sent = send_onboarding()
        assert sent == 0

    def test_unsubscribed_lead_skipped(self):
        lead = _make_lead()
        lead.unsubscribed_at = timezone.now()
        lead.save()
        sent = send_onboarding()
        assert sent == 0

    def test_nl_subject(self):
        lead = _make_lead(email="nl@example.com", lang="nl")
        sent = send_onboarding()
        assert sent == 1


class TestUninstallFeedback:
    def test_get_renders(self):
        resp = Client().get("/feedback/uninstall/", **M)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "uninstall-form" in html or "reason" in html

    def test_nl_get_renders(self):
        resp = Client().get("/nl/feedback/uninstall/", **M)
        assert resp.status_code == 200

    def test_post_creates_feedback(self):
        resp = Client().post("/feedback/uninstall/", {
            "email": "x@example.com",
            "shop_domain": "x.myshopify.com",
            "reason": "too_expensive",
            "comment": "test comment",
            "lang": "en",
        }, **M)
        assert resp.status_code == 200
        assert UninstallFeedback.objects.filter(reason="too_expensive").exists()

    def test_post_with_honeypot_silently_dropped(self):
        resp = Client().post("/feedback/uninstall/", {
            "email": "bot@example.com",
            "reason": "other",
            "website": "spam",
        }, **M)
        assert resp.status_code == 200
        assert not UninstallFeedback.objects.filter(email="bot@example.com").exists()

    def test_invalid_reason_shows_error(self):
        resp = Client().post("/feedback/uninstall/", {
            "email": "y@example.com",
            "reason": "not_a_valid_reason",
        }, **M)
        assert resp.status_code == 200
        assert not UninstallFeedback.objects.exists()
