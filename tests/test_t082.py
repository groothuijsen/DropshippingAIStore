"""Tests for T-082: GPSR validation + publish gate."""

from pathlib import Path

from apps.compliance.gpsr import (
    GpsrInfo,
    check_gpsr_for_publish,
    get_gpsr_compliance_score_impact,
)

EXTENSIONS_DIR = Path(__file__).parent.parent / "extensions" / "theme-blocks"
BLOCK_FILE = EXTENSIONS_DIR / "blocks" / "mq-gpsr.liquid"


# ── GpsrInfo completeness tests ───────────────────────────────────────────


class TestGpsrCompleteness:
    def test_empty_not_complete(self):
        gpsr = GpsrInfo()
        assert gpsr.complete is False

    def test_manufacturer_only_not_complete(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME Corp",
            manufacturer_address="123 Main St",
            manufacturer_email="info@acme.com",
        )
        assert gpsr.complete is False  # missing product_identifier + warnings

    def test_manufacturer_in_eu_no_rp_needed(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME Corp",
            manufacturer_address="123 Main St",
            manufacturer_email="info@acme.com",
            manufacturer_in_eu=True,
            product_identifier="SKU-123",
            warnings="Handle with care",
        )
        assert gpsr.complete is True

    def test_manufacturer_outside_eu_requires_rp(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME Corp",
            manufacturer_address="123 Main St",
            manufacturer_email="info@acme.com",
            manufacturer_in_eu=False,
            product_identifier="SKU-123",
            warnings="Handle with care",
        )
        assert gpsr.complete is False  # missing eu_rp fields

    def test_manufacturer_outside_eu_with_rp_complete(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME Corp",
            manufacturer_address="123 Main St",
            manufacturer_email="info@acme.com",
            manufacturer_in_eu=False,
            eu_rp_name="EU Import BV",
            eu_rp_address="456 EU Ave",
            eu_rp_email="eu@import.com",
            product_identifier="SKU-123",
            warnings="Handle with care",
        )
        assert gpsr.complete is True

    def test_no_warnings_confirmed(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME Corp",
            manufacturer_address="123 Main St",
            manufacturer_email="info@acme.com",
            manufacturer_in_eu=True,
            product_identifier="SKU-123",
            no_warnings_confirmed=True,
        )
        assert gpsr.complete is True

    def test_missing_fields_list(self):
        gpsr = GpsrInfo()
        missing = gpsr.missing_fields
        assert "manufacturer_name" in missing
        assert "product_identifier" in missing
        assert "warnings" in missing

    def test_missing_fields_empty_when_complete(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME",
            manufacturer_address="123 Main",
            manufacturer_email="a@b.com",
            manufacturer_in_eu=True,
            product_identifier="SKU-1",
            warnings="Careful",
        )
        assert gpsr.missing_fields == []


# ── Metafield serialization tests ─────────────────────────────────────────


class TestMetafieldSerialization:
    def test_roundtrip(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME Corp",
            manufacturer_address="123 Main St",
            manufacturer_email="info@acme.com",
            manufacturer_in_eu=False,
            eu_rp_name="EU Import",
            eu_rp_address="456 EU Ave",
            eu_rp_email="eu@import.com",
            product_identifier="SKU-123",
            warnings="Handle with care",
            content_locale="nl",
        )
        data = gpsr.to_metafield()
        restored = GpsrInfo.from_metafield(data)
        assert restored == gpsr

    def test_from_none(self):
        gpsr = GpsrInfo.from_metafield(None)
        assert gpsr.complete is False

    def test_from_empty_dict(self):
        gpsr = GpsrInfo.from_metafield({})
        assert gpsr.complete is False


# ── Publish gate tests ────────────────────────────────────────────────────


class TestPublishGate:
    def test_publish_allowed_when_complete(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME",
            manufacturer_address="123 Main",
            manufacturer_email="a@b.com",
            manufacturer_in_eu=True,
            product_identifier="SKU-1",
            warnings="Careful",
        )
        allowed, message = check_gpsr_for_publish(gpsr)
        assert allowed is True
        assert message == ""

    def test_publish_blocked_when_incomplete(self):
        gpsr = GpsrInfo()
        allowed, message = check_gpsr_for_publish(gpsr)
        assert allowed is False
        assert "GPSR incomplete" in message

    def test_publish_blocked_message_lists_missing(self):
        gpsr = GpsrInfo(manufacturer_name="ACME")
        allowed, message = check_gpsr_for_publish(gpsr)
        assert allowed is False
        assert "manufacturer_address" in message


# ── Compliance score tests ────────────────────────────────────────────────


class TestComplianceScoreImpact:
    def test_incomplete_costs_20_points(self):
        gpsr = GpsrInfo()
        impact = get_gpsr_compliance_score_impact(gpsr)
        assert impact == -20

    def test_complete_costs_nothing(self):
        gpsr = GpsrInfo(
            manufacturer_name="ACME",
            manufacturer_address="123 Main",
            manufacturer_email="a@b.com",
            manufacturer_in_eu=True,
            product_identifier="SKU-1",
            warnings="Careful",
        )
        impact = get_gpsr_compliance_score_impact(gpsr)
        assert impact == 0


# ── Liquid block tests ────────────────────────────────────────────────────


class TestMqGpsrLiquid:
    def test_block_exists(self):
        assert BLOCK_FILE.exists()

    def test_shows_manufacturer(self):
        content = BLOCK_FILE.read_text()
        assert "manufacturer_name" in content
        assert "manufacturer_address" in content
        assert "manufacturer_email" in content

    def test_shows_responsible_person(self):
        content = BLOCK_FILE.read_text()
        assert "eu_rp_name" in content
        assert "eu_rp_address" in content
        assert "eu_rp_email" in content

    def test_shows_product_identifier(self):
        content = BLOCK_FILE.read_text()
        assert "product_identifier" in content

    def test_shows_warnings(self):
        content = BLOCK_FILE.read_text()
        assert "warnings" in content

    def test_renders_nothing_if_missing(self):
        content = BLOCK_FILE.read_text()
        assert "{%- if gpsr -%}" in content

    def test_uses_app_namespace(self):
        content = BLOCK_FILE.read_text()
        assert "$app:mosaiq" in content
