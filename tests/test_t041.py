"""Tests for T-041: image fidelity check."""

from unittest.mock import MagicMock, patch

from apps.ai.fidelity import (
    MAX_FIDELITY_ATTEMPTS,
    MAX_ISSUES,
    FidelityResult,
    check_and_retry,
    check_fidelity,
)

# ── FidelityResult tests ──────────────────────────────────────────────────


class TestFidelityResult:
    def test_passed(self):
        result = FidelityResult(same_product=True)
        assert result.passed is True

    def test_failed_different_product(self):
        result = FidelityResult(same_product=False, issues=["Different shape"])
        assert result.passed is False

    def test_failed_with_error(self):
        result = FidelityResult(same_product=True, error="API error")
        assert result.passed is False

    def test_issues_capped_at_max(self):
        issues = [f"Issue {i}" for i in range(MAX_ISSUES + 5)]
        result = FidelityResult(same_product=False, issues=issues[:MAX_ISSUES])
        assert len(result.issues) <= MAX_ISSUES


# ── Fidelity check tests ──────────────────────────────────────────────────


class TestCheckFidelity:
    @patch("apps.ai.anthropic_client.AnthropicClient")
    def test_same_product_passes(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.call.return_value = (FidelityResult(same_product=True, issues=[]), {"cost": 0.01})
        result = check_fidelity(b"ref", b"gen")
        assert result.passed is True

    @patch("apps.ai.anthropic_client.AnthropicClient")
    def test_different_product_fails(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.call.return_value = (
            FidelityResult(same_product=False, issues=["Different color", "Extra parts"]),
            {"cost": 0.01},
        )
        result = check_fidelity(b"ref", b"gen")
        assert result.passed is False
        assert "Different color" in result.issues

    @patch("apps.ai.anthropic_client.AnthropicClient")
    def test_call_failure_returns_error(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.call.side_effect = RuntimeError("API error")
        result = check_fidelity(b"ref", b"gen")
        assert result.passed is False
        assert result.error == "API error"

    @patch("apps.ai.anthropic_client.AnthropicClient")
    def test_issues_capped(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.call.return_value = (
            FidelityResult(same_product=False, issues=[f"Issue {i}" for i in range(20)]),
            {"cost": 0.01},
        )
        result = check_fidelity(b"ref", b"gen")
        assert len(result.issues) <= MAX_ISSUES


# ── Retry logic tests ─────────────────────────────────────────────────────


class TestCheckAndRetry:
    @patch("apps.ai.fidelity.check_fidelity")
    def test_first_attempt_passes(self, mock_check):
        mock_check.return_value = FidelityResult(same_product=True)
        passed, image, result = check_and_retry(
            b"ref",
            b"gen",
            lambda: b"new_gen",
        )
        assert passed is True
        assert image == b"gen"
        assert mock_check.call_count == 1

    @patch("apps.ai.fidelity.check_fidelity")
    def test_retry_on_failure(self, mock_check):
        mock_check.side_effect = [
            FidelityResult(same_product=False, issues=["Bad"]),
            FidelityResult(same_product=True),
        ]
        passed, image, result = check_and_retry(
            b"ref",
            b"gen",
            lambda: b"new_gen",
        )
        assert passed is True
        assert image == b"new_gen"
        assert mock_check.call_count == 2

    @patch("apps.ai.fidelity.check_fidelity")
    def test_both_attempts_fail(self, mock_check):
        mock_check.side_effect = [
            FidelityResult(same_product=False, issues=["Bad"]),
            FidelityResult(same_product=False, issues=["Still bad"]),
        ]
        passed, image, result = check_and_retry(
            b"ref",
            b"gen",
            lambda: b"new_gen",
        )
        assert passed is False
        assert image == b""
        assert mock_check.call_count == 2

    @patch("apps.ai.fidelity.check_fidelity")
    def test_retry_generation_fails(self, mock_check):
        mock_check.return_value = FidelityResult(same_product=False, issues=["Bad"])
        passed, image, result = check_and_retry(
            b"ref",
            b"gen",
            lambda: (_ for _ in ()).throw(RuntimeError("Gen error")),
        )
        assert passed is False
        assert result.error == "Gen error"


# ── Constants tests ───────────────────────────────────────────────────────


class TestConstants:
    def test_max_attempts(self):
        assert MAX_FIDELITY_ATTEMPTS == 2

    def test_max_issues(self):
        assert MAX_ISSUES == 10
