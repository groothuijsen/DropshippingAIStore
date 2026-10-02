"""T-153 — pricing table from plans.py + comparison freshness (F19-4, F19-11)."""

from datetime import date
from pathlib import Path

import pytest
from django.test import Client

from apps.marketing.freshness import HIDE_AFTER_DAYS, REVIEW_AFTER_DAYS, annotate_comparisons, comparison_state

pytestmark = pytest.mark.django_db

MARKETING = {"HTTP_HOST": "shopify.mosaiq.marketing"}


@pytest.fixture(autouse=True)
def _allow_hosts(settings):
    settings.ALLOWED_HOSTS = ["*"]


class TestComparisonFreshness:
    def test_boundaries(self):
        today = date(2026, 10, 3)
        assert comparison_state("2026-10-03", today) == ("fresh", 0)
        assert comparison_state("2026-07-06", today)[1] == REVIEW_AFTER_DAYS - 1
        assert comparison_state("2026-07-05", today)[0] == "review"
        assert comparison_state("2026-06-06", today)[1] == HIDE_AFTER_DAYS - 1
        assert comparison_state("2026-06-05", today)[0] == "expired"

    def test_annotate_sets_state(self):
        sections = [{"type": "comparison", "last_checked": "2026-10-03", "rows": [], "sources": []},
                    {"type": "hero"}]
        annotate_comparisons(sections, date(2027, 2, 1))
        assert sections[0]["comparison_state"] == "expired" and sections[0]["comparison_age_days"] == 121
        assert "comparison_state" not in sections[1]


class TestPricingRendersFromCode:
    def test_pricing_page_shows_plans_from_plans_py(self):
        html = Client().get("/pricing/", **MARKETING).content.decode()
        for name in ("Mosaiq Starter", "Mosaiq Pro", "Mosaiq Agency"):
            assert name in html
        assert "29" in html and "59" in html and "149" in html
        assert "All compliance features in every plan" in html

    def test_copy_never_types_prices(self):
        for lang in ("en", "nl"):
            text = Path(f"content/marketing/{lang}/pricing.md").read_text()
            for typed in ("$29", "$59", "$149", "29,", "€"):
                assert typed not in text, f"typed price {typed!r} in {lang}/pricing.md"

    def test_nl_pricing_page(self):
        html = Client().get("/nl/prijzen/", **MARKETING).content.decode()
        assert "Mosaiq Starter" in html and "vroege-toegang" in html
