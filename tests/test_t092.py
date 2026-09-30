"""Tests for T-092: release checklist + lighthouse check script."""

from pathlib import Path
from unittest.mock import patch

from scripts.lighthouse_check import check_url, get_metric_value, get_performance_score


class TestReleaseChecklist:
    def test_checklist_exists(self):
        path = Path(__file__).parent.parent / "docs" / "release-checklist.md"
        assert path.exists()

    def test_checklist_covers_all_sections(self):
        path = Path(__file__).parent.parent / "docs" / "release-checklist.md"
        content = path.read_text()
        assert "Install" in content
        assert "Import" in content
        assert "Generate" in content
        assert "Theme Blocks" in content
        assert "Offers" in content
        assert "Compliance" in content
        assert "Uninstall" in content
        assert "Lighthouse" in content

    def test_checklist_lighthouse_threshold(self):
        path = Path(__file__).parent.parent / "docs" / "release-checklist.md"
        content = path.read_text()
        assert "≥ 85" in content


class TestLighthouseCheck:
    def _mock_report(self, score: float = 0.92) -> dict:
        return {
            "categories": {"performance": {"score": score}},
            "audits": {
                "largest-contentful-paint": {"numericValue": 1800},
                "first-contentful-paint": {"numericValue": 900},
                "cumulative-layout-shift": {"numericValue": 0.05},
            },
        }

    def test_get_performance_score(self):
        report = self._mock_report(0.87)
        assert get_performance_score(report) == 0.87

    def test_get_performance_score_missing(self):
        assert get_performance_score({}) == 0.0

    def test_get_metric_value(self):
        report = self._mock_report()
        assert get_metric_value(report, "largest-contentful-paint") == 1800

    def test_get_metric_value_missing(self):
        report = self._mock_report()
        assert get_metric_value(report, "nonexistent") is None

    @patch("scripts.lighthouse_check.run_lighthouse")
    def test_check_url_pass(self, mock_run):
        mock_run.return_value = self._mock_report(0.92)
        result = check_url("https://example.com/pdp", min_score=85)
        assert result["passed"] is True
        assert result["score"] == 92
        assert result["lcp_ms"] == 1800
        assert result["cls"] == 0.05

    @patch("scripts.lighthouse_check.run_lighthouse")
    def test_check_url_fail(self, mock_run):
        mock_run.return_value = self._mock_report(0.60)
        result = check_url("https://example.com/pdp", min_score=85)
        assert result["passed"] is False
        assert result["score"] == 60

    @patch("scripts.lighthouse_check.run_lighthouse")
    def test_check_url_boundary(self, mock_run):
        mock_run.return_value = self._mock_report(0.85)
        result = check_url("https://example.com/pdp", min_score=85)
        assert result["passed"] is True

    @patch("scripts.lighthouse_check.run_lighthouse")
    def test_check_url_desktop(self, mock_run):
        mock_run.return_value = self._mock_report(0.95)
        result = check_url("https://example.com/pdp", min_score=85, mobile=False)
        assert result["mobile"] is False
        mock_run.assert_called_once_with("https://example.com/pdp", mobile=False)
