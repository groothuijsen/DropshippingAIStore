"""Tests for T-091: evalset + eval runner."""

from pathlib import Path
from unittest.mock import MagicMock

from tests.evalset.run_eval import (
    check_fabricated_specs,
    check_length_overruns,
    load_evalset,
    write_report,
)


class TestEvalset:
    def test_evalset_exists(self):
        path = Path(__file__).parent / "evalset" / "eval_products.json"
        assert path.exists()

    def test_evalset_30_products(self):
        products = load_evalset()
        assert len(products) >= 30  # 30 base + 5 long-delivery cases (T-142)

    def test_evalset_categories(self):
        products = load_evalset()
        wellness = [p for p in products if p["category"] == "wellness"]
        car = [p for p in products if p["category"] == "car_accessories"]
        pod = [p for p in products if p["category"] == "pod_merch"]
        assert len(wellness) >= 10
        assert len(car) >= 10
        assert len(pod) >= 10

    def test_evalset_languages(self):
        products = load_evalset()
        langs = {p["language"] for p in products}
        assert langs == {"nl", "en", "de"}

    def test_evalset_import_result_shape(self):
        products = load_evalset()
        for p in products:
            assert "id" in p
            assert "title" in p
            assert "description" in p
            assert "price" in p
            assert "currency" in p
            assert "specs" in p
            assert "language" in p


class TestFabricatedSpecs:
    def test_no_fabricated(self):
        input_specs = {"Gewicht": "200 g", "Herkomst": "Peru"}
        output_specs = [{"label": "Gewicht", "value": "200 g"}]
        fabricated = check_fabricated_specs(output_specs, input_specs)
        assert fabricated == []

    def test_fabricated_detected(self):
        input_specs = {"Gewicht": "200 g"}
        output_specs = [
            {"label": "Gewicht", "value": "200 g"},
            {"label": "Fabrikant", "value": "ACME"},
        ]
        fabricated = check_fabricated_specs(output_specs, input_specs)
        assert fabricated == ["Fabrikant"]

    def test_case_insensitive(self):
        input_specs = {"gewicht": "200 g"}
        output_specs = [{"label": "Gewicht", "value": "200 g"}]
        fabricated = check_fabricated_specs(output_specs, input_specs)
        assert fabricated == []


class TestLengthOverruns:
    def test_no_overruns(self):
        payload = MagicMock()
        payload.seo_title = "Short title"
        payload.seo_description = "Short description"
        payload.sections = []
        overruns = check_length_overruns(payload)
        assert overruns == []

    def test_seo_title_overrun(self):
        payload = MagicMock()
        payload.seo_title = "x" * 61
        payload.seo_description = "Short"
        payload.sections = []
        overruns = check_length_overruns(payload)
        assert "seo_title" in overruns

    def test_seo_description_overrun(self):
        payload = MagicMock()
        payload.seo_title = "Short"
        payload.seo_description = "x" * 156
        payload.sections = []
        overruns = check_length_overruns(payload)
        assert "seo_description" in overruns


class TestWriteReport:
    def test_report_written(self, tmp_path):
        eval_output = {
            "results": [
                {
                    "id": "test-01",
                    "category": "wellness",
                    "language": "nl",
                    "schema_valid": True,
                    "block_count": 0,
                    "fabricated_specs": [],
                    "overruns": [],
                    "cost_usd": 0.05,
                    "duration_s": 2.1,
                    "error": None,
                },
            ],
            "summary": {
                "total": 1,
                "schema_valid": 1,
                "total_blocks": 0,
                "total_fabricated_specs": 0,
                "total_overruns": 0,
                "total_cost_usd": 0.05,
                "total_duration_s": 2.1,
                "errors": 0,
            },
        }
        import tests.evalset.run_eval as m

        original = m.REPORT_DIR
        m.REPORT_DIR = tmp_path
        try:
            report = write_report(eval_output)
            assert report.exists()
            content = report.read_text()
            assert "PASS" in content
        finally:
            m.REPORT_DIR = original

    def test_report_fail(self, tmp_path):
        eval_output = {
            "results": [],
            "summary": {
                "total": 0,
                "schema_valid": 0,
                "total_blocks": 3,
                "total_fabricated_specs": 1,
                "total_overruns": 0,
                "total_cost_usd": 0,
                "total_duration_s": 0,
                "errors": 1,
            },
        }
        import tests.evalset.run_eval as m

        original = m.REPORT_DIR
        m.REPORT_DIR = tmp_path
        try:
            report = write_report(eval_output)
            content = report.read_text()
            assert "FAIL" in content
        finally:
            m.REPORT_DIR = original
