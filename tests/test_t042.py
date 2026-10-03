"""Tests for T-042: C2PA signing + staged upload + fileCreate + alt text + AI label."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.ai.c2pa import MOSAIQ_AGENT, c2pa_available, sign_image, verify_manifest
from apps.ai.image_upload import (
    MAX_READY_WAIT_SECONDS,
    build_alt_text,
    upload_image,
)
from apps.core.crypto import encrypt_token
from apps.core.models import Shop, ShopStatus


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


# ── C2PA tests ────────────────────────────────────────────────────────────


class TestC2PA:
    def test_c2pa_available_returns_bool(self):
        result = c2pa_available()
        assert isinstance(result, bool)

    def test_sign_image_dev_mode_returns_none(self):
        """Without c2pa-python, sign_image returns None (do not publish)."""
        with patch("apps.ai.c2pa.c2pa_available", return_value=False):
            result = sign_image(b"fake-image", "/tmp/test.png")
            assert result is None

    def test_verify_manifest_dev_mode_returns_none(self):
        with patch("apps.ai.c2pa.c2pa_available", return_value=False):
            result = verify_manifest("/tmp/test.png")
            assert result is None

    def test_sign_image_failure_returns_none(self):
        """C2PA signing failure → None (do not publish)."""
        with (
            patch("apps.ai.c2pa.c2pa_available", return_value=True),
            patch("c2pa.Builder", side_effect=RuntimeError("Sign error")),
        ):
            result = sign_image(b"fake-image", "/tmp/test.png")
            assert result is None

    def test_mosaiq_agent_constant(self):
        assert MOSAIQ_AGENT == "Mosaiq"


# ── Alt text tests ────────────────────────────────────────────────────────


class TestAltText:
    def test_short_description(self):
        assert build_alt_text("A great product") == "A great product"

    def test_empty_description(self):
        assert build_alt_text("") == ""

    def test_long_description_truncated(self):
        long_desc = "This is a very long product description " * 5
        result = build_alt_text(long_desc)
        assert len(result) <= 125

    def test_truncation_at_word_boundary(self):
        long_desc = "word " * 30  # 150 chars
        result = build_alt_text(long_desc)
        assert len(result) <= 125
        assert not result.endswith(" ")

    def test_exactly_125_chars(self):
        desc = "x" * 125
        assert build_alt_text(desc) == desc

    def test_126_chars_truncated(self):
        desc = "x" * 126
        result = build_alt_text(desc)
        assert len(result) < 126


# ── Upload tests ──────────────────────────────────────────────────────────


class TestUploadImage:
    @patch("apps.ai.image_upload._wait_until_ready", return_value=True)
    @patch("apps.ai.image_upload.httpx.Client")
    @patch("apps.ai.image_upload._get_client")
    def test_upload_success(self, mock_get_client, mock_http, mock_wait, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [
            {
                "stagedUploadsCreate": {
                    "stagedTargets": [
                        {
                            "url": "https://upload.shopify.com",
                            "resourceUrl": "https://cdn.shopify.com/file.png",
                            "parameters": [{"name": "key", "value": "file.png"}],
                        }
                    ]
                }
            },
            {"fileCreate": {"files": [{"id": "gid://shopify/MediaImage/1", "status": "UPLOADING"}]}},
        ]
        mock_http.return_value.__enter__.return_value.post.return_value.status_code = 200

        result = upload_image(shop, b"fake-image", "file.png", alt="Test alt")
        assert result.success is True
        assert result.file_gid == "gid://shopify/MediaImage/1"

    @patch("apps.ai.image_upload._get_client")
    def test_upload_no_staged_targets(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.return_value = {"stagedUploadsCreate": {"stagedTargets": []}}

        result = upload_image(shop, b"fake-image", "file.png")
        assert result.success is False
        assert "No staged targets" in result.error

    @patch("apps.ai.image_upload._wait_until_ready", return_value=False)
    @patch("apps.ai.image_upload.httpx.Client")
    @patch("apps.ai.image_upload._get_client")
    def test_upload_returns_gid_synchronously(self, mock_get_client, mock_http, mock_wait, shop):
        """2026-07: File has no `status` — fileCreate gid is usable immediately."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [
            {
                "stagedUploadsCreate": {
                    "stagedTargets": [
                        {
                            "url": "https://upload.shopify.com",
                            "resourceUrl": "https://cdn.shopify.com/file.png",
                            "parameters": [],
                        }
                    ]
                }
            },
            {"fileCreate": {"files": [{"id": "gid://shopify/MediaImage/1"}]}},
        ]
        mock_http.return_value.__enter__.return_value.post.return_value.status_code = 201

        result = upload_image(shop, b"fake-image", "file.png")
        assert result.success is True
        assert result.file_gid == "gid://shopify/MediaImage/1"
        mock_wait.assert_not_called()

    @patch("apps.ai.image_upload._get_client")
    def test_upload_exception(self, mock_get_client, shop):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = RuntimeError("API error")

        result = upload_image(shop, b"fake-image", "file.png")
        assert result.success is False
        assert "API error" in result.error

    @patch("apps.ai.image_upload._wait_until_ready", return_value=True)
    @patch("apps.ai.image_upload.httpx.Client")
    @patch("apps.ai.image_upload._get_client")
    def test_upload_file_ready_immediately(self, mock_get_client, mock_http, mock_wait, shop):
        """If fileCreate returns READY, no polling needed."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.execute.side_effect = [
            {
                "stagedUploadsCreate": {
                    "stagedTargets": [
                        {
                            "url": "https://upload.shopify.com",
                            "resourceUrl": "https://cdn.shopify.com/file.png",
                            "parameters": [],
                        }
                    ]
                }
            },
            {"fileCreate": {"files": [{"id": "gid://shopify/MediaImage/1", "status": "READY"}]}},
        ]
        mock_http.return_value.__enter__.return_value.post.return_value.status_code = 200

        result = upload_image(shop, b"fake-image", "file.png")
        assert result.success is True
        # _wait_until_ready should not be called (file already READY)
        mock_wait.assert_not_called()


# ── Constants tests ───────────────────────────────────────────────────────


class TestConstants:
    def test_max_ready_wait(self):
        assert MAX_READY_WAIT_SECONDS == 60
