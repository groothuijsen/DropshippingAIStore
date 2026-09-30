"""Tests for T-043: C2PA CDN verification script."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from verify_c2pa import check_c2patool, check_exiftool, verify_file

# ── c2patool check tests ──────────────────────────────────────────────────


class TestC2PATool:
    @patch("subprocess.run")
    def test_manifest_found(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Manifest: c2pa manifest found\nSigned: true",
            stderr="",
            returncode=0,
        )
        result = check_c2patool("/tmp/test.png")
        assert result["has_manifest"] is True

    @patch("subprocess.run")
    def test_no_manifest(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="No C2PA data found",
            stderr="",
            returncode=0,
        )
        result = check_c2patool("/tmp/test.png")
        assert result["has_manifest"] is False

    @patch("subprocess.run")
    def test_tool_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = check_c2patool("/tmp/test.png")
        assert result["has_manifest"] is None
        assert "not installed" in result["error"]


# ── exiftool check tests ──────────────────────────────────────────────────


class TestExifTool:
    @patch("subprocess.run")
    def test_c2pa_found(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="C2PA-Hash: abc123\nManifest: present",
            stderr="",
            returncode=0,
        )
        result = check_exiftool("/tmp/test.png")
        assert result["has_c2pa"] is True

    @patch("subprocess.run")
    def test_no_c2pa(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="JPEG image data\nExif version: 0231",
            stderr="",
            returncode=0,
        )
        result = check_exiftool("/tmp/test.png")
        assert result["has_c2pa"] is False

    @patch("subprocess.run")
    def test_tool_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = check_exiftool("/tmp/test.png")
        assert result["has_c2pa"] is None


# ── verify_file tests ─────────────────────────────────────────────────────


class TestVerifyFile:
    def test_local_file_with_manifest(self):
        with (
            patch("verify_c2pa.check_c2patool", return_value={"has_manifest": True}),
            patch("verify_c2pa.check_exiftool", return_value={"has_c2pa": True, "has_manifest": True}),
        ):
            result = verify_file("/tmp/test.png")
            assert result["has_manifest"] is True
            assert result["variant"] == ""

    def test_local_file_no_manifest(self):
        with (
            patch("verify_c2pa.check_c2patool", return_value={"has_manifest": False}),
            patch("verify_c2pa.check_exiftool", return_value={"has_c2pa": False, "has_manifest": False}),
        ):
            result = verify_file("/tmp/test.png")
            assert result["has_manifest"] is False

    def test_cdn_variant_url(self):
        """URL with variant query string."""
        with (
            patch("verify_c2pa.check_c2patool", return_value={"has_manifest": False}),
            patch("verify_c2pa.check_exiftool", return_value={"has_c2pa": False, "has_manifest": False}),
            patch("httpx.get") as mock_get,
        ):
            mock_get.return_value = MagicMock(
                content=b"fake-image",
                raise_for_return=lambda: None,
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = verify_file(
                "https://cdn.shopify.com/file.png",
                variant="width=800&format=webp",
            )
            # Check that the URL was constructed correctly
            assert "width=800" in result.get("url", "")

    def test_cdn_variant_existing_query(self):
        """URL that already has a query string."""
        with (
            patch("verify_c2pa.check_c2patool", return_value={"has_manifest": False}),
            patch("verify_c2pa.check_exiftool", return_value={"has_c2pa": False, "has_manifest": False}),
            patch("httpx.get") as mock_get,
        ):
            mock_get.return_value = MagicMock(content=b"fake")
            mock_get.return_value.raise_for_status = MagicMock()
            result = verify_file(
                "https://cdn.shopify.com/file.png?v=123",
                variant="width=800",
            )
            # Should use & separator, not ?
            assert "v=123&width=800" in result.get("url", "")


# ── Integration tests ─────────────────────────────────────────────────────


class TestIntegration:
    @patch("subprocess.run")
    def test_full_check_local_file(self, mock_run):
        """Full check with both tools on a local file."""
        mock_run.return_value = MagicMock(
            stdout="Manifest found\nC2PA-Hash: abc",
            stderr="",
            returncode=0,
        )
        result = verify_file("/tmp/test.png")
        assert result["has_manifest"] is True

    @patch("subprocess.run")
    def test_mixed_results(self, mock_run):
        """c2patool finds manifest but exiftool doesn't (or vice versa)."""
        mock_run.side_effect = [
            MagicMock(stdout="Manifest found", stderr="", returncode=0),  # c2patool
            MagicMock(stdout="No C2PA data", stderr="", returncode=0),  # exiftool
        ]
        result = verify_file("/tmp/test.png")
        # Either tool finding manifest is enough
        assert result["has_manifest"] is True
