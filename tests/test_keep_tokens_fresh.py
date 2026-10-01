"""Tests for keep_tokens_fresh: hourly beat task that keeps access tokens valid.

Root cause of the dev-store 401 loop: the task only selected shops whose
REFRESH token expires within 14 days, but the problem is the ACCESS token
expiring (~hourly in dev). Nothing refreshed it, so every queued task after
expiry failed with Auth failed (401).
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.core.models import Shop, ShopStatus
from apps.core.tasks import keep_tokens_fresh


@pytest.fixture
def active_shop(db):
    """Active shop whose access token is still valid for hours."""
    now = timezone.now()
    return Shop.objects.create(
        domain="fresh.myshopify.com",
        shopify_gid="gid://shopify/Shop/900",
        access_token_encrypted=b"placeholder",
        access_token_expires_at=now + timedelta(hours=6),
        refresh_token_expires_at=now + timedelta(days=60),
        status=ShopStatus.ACTIVE,
        needs_reauth=False,
    )


@pytest.mark.django_db
class TestKeepTokensFresh:
    def test_refreshes_shop_with_expiring_access_token(self, active_shop):
        """An access token expiring within the threshold must be refreshed,
        even when the refresh token is still valid for months."""
        active_shop.access_token_expires_at = timezone.now() + timedelta(minutes=30)
        active_shop.save(update_fields=["access_token_expires_at"])

        with patch("apps.core.tasks.refresh_access_token") as mock_refresh:
            mock_refresh.return_value = True
            result = keep_tokens_fresh()

        assert mock_refresh.called
        assert result["refreshed"] == 1

    def test_skips_shop_with_fresh_access_token(self, active_shop):
        """Access token valid for hours → no refresh call."""
        with patch("apps.core.tasks.refresh_access_token") as mock_refresh:
            result = keep_tokens_fresh()

        assert not mock_refresh.called
        assert result == {"refreshed": 0, "failed": 0}

    def test_still_covers_refresh_token_expiry(self, active_shop):
        """The original 14-day refresh-token window must keep working."""
        active_shop.refresh_token_expires_at = timezone.now() + timedelta(days=5)
        active_shop.save(update_fields=["refresh_token_expires_at"])

        with patch("apps.core.tasks.refresh_access_token") as mock_refresh:
            mock_refresh.return_value = True
            result = keep_tokens_fresh()

        assert mock_refresh.called
        assert result["refreshed"] == 1

    def test_needs_reauth_shop_is_skipped(self, active_shop):
        """Shops flagged needs_reauth are never touched by the task."""
        active_shop.needs_reauth = True
        active_shop.access_token_expires_at = timezone.now() + timedelta(minutes=30)
        active_shop.save()

        with patch("apps.core.tasks.refresh_access_token") as mock_refresh:
            result = keep_tokens_fresh()

        assert not mock_refresh.called
        assert result == {"refreshed": 0, "failed": 0}

    def test_failed_refresh_is_counted(self, active_shop):
        active_shop.access_token_expires_at = timezone.now() + timedelta(minutes=30)
        active_shop.save(update_fields=["access_token_expires_at"])

        with patch("apps.core.tasks.refresh_access_token") as mock_refresh:
            mock_refresh.return_value = False
            result = keep_tokens_fresh()

        assert result == {"refreshed": 0, "failed": 1}

    @patch("apps.core.tasks.refresh_access_token")
    def test_refresh_failure_does_not_raise(self, mock_refresh):
        """An exception inside refresh must be caught and counted, never
        propagated — the task is a safety net and must not crash the worker."""
        mock_refresh.side_effect = RuntimeError("boom")
        result = keep_tokens_fresh()
        assert result == {"refreshed": 0, "failed": 0}
