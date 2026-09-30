"""Tests for T-086: support page + contact form + FAQ."""

from datetime import timedelta
from unittest.mock import patch

import jwt
import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus
from apps.support.forms import ContactForm
from apps.support.views import FAQ_ITEMS


def _make_token(shop_domain: str = "test-store.myshopify.com") -> str:
    """Generate a valid session token for middleware."""
    from django.conf import settings

    dest = f"https://{shop_domain}"
    payload = {
        "dest": dest,
        "iss": f"{dest}/admin",
        "aud": settings.SHOPIFY_API_KEY,
        "exp": (timezone.now() + timedelta(hours=1)).timestamp(),
    }
    return jwt.encode(payload, settings.SHOPIFY_API_SECRET, algorithm="HS256")


@pytest.fixture
def shop(db):
    now = timezone.now()
    return Shop.objects.create(
        domain="test-store.myshopify.com",
        shopify_gid="gid://shopify/Shop/123",
        access_token_encrypted=encrypt_token("shpat_test_token"),
        access_token_expires_at=now + timedelta(hours=1),
        refresh_token_encrypted=encrypt_token("shpat_refresh_token"),
        refresh_token_expires_at=now + timedelta(days=90),
        currency_code="EUR",
        status=ShopStatus.ACTIVE,
    )


class TestContactForm:
    def test_valid(self):
        form = ContactForm(
            data={
                "subject": "Test question",
                "message": "This is a test message that is long enough.",
                "shop_domain": "test.myshopify.com",
            }
        )
        assert form.is_valid()

    def test_missing_subject(self):
        form = ContactForm(
            data={
                "subject": "",
                "message": "This is a test message that is long enough.",
            }
        )
        assert not form.is_valid()

    def test_message_too_short(self):
        form = ContactForm(
            data={
                "subject": "Test",
                "message": "Short",
            }
        )
        assert not form.is_valid()

    def test_shop_domain_optional(self):
        form = ContactForm(
            data={
                "subject": "Test",
                "message": "This is a test message that is long enough.",
            }
        )
        assert form.is_valid()


class TestFAQ:
    def test_faq_items_exist(self):
        assert len(FAQ_ITEMS) >= 5

    def test_faq_all_langs(self):
        for item in FAQ_ITEMS:
            assert "nl" in item["question"]
            assert "de" in item["question"]
            assert "en" in item["question"]
            assert "nl" in item["answer"]
            assert "de" in item["answer"]
            assert "en" in item["answer"]


class TestSupportView:
    def test_get_support_page(self, db):
        client = Client()
        token = _make_token()
        response = client.get(f"{reverse('support:index')}?id_token={token}")
        assert response.status_code == 200
        assert b"mq-support" in response.content

    @patch("apps.support.views.send_mail")
    def test_post_contact_form(self, mock_send, db):
        client = Client()
        token = _make_token()
        response = client.post(
            f"{reverse('support:index')}?id_token={token}",
            {
                "subject": "Test question",
                "message": "This is a test message that is long enough.",
                "shop_domain": "test.myshopify.com",
            },
        )
        assert response.status_code == 200
        mock_send.assert_called_once()

    @patch("apps.support.views.send_mail")
    def test_post_invalid_form(self, mock_send, db):
        client = Client()
        token = _make_token()
        response = client.post(
            f"{reverse('support:index')}?id_token={token}",
            {
                "subject": "",
                "message": "Short",
            },
        )
        assert response.status_code == 200
        mock_send.assert_not_called()
