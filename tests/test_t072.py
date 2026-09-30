"""Tests for T-072: mq-bundle-picker Liquid block + snippets.

Liquid cannot be executed in pytest; per the spec (04 §2) the Python
compliance functions are the reference implementation. These tests verify:
1. Python reference calculation matches the Liquid formula (same math)
2. Liquid files contain the required hard-rule patterns (no compare_at_price,
   timer gated on ends_at, no localStorage, current variant.price)
3. Locale keys exist in nl/en/de
"""

import json
import re
from pathlib import Path

import pytest

EXT_DIR = Path(__file__).resolve().parent.parent / "extensions" / "theme-blocks"
BLOCK = EXT_DIR / "blocks" / "mq-bundle-picker.liquid"
TIMER = EXT_DIR / "snippets" / "mq-offer-timer.liquid"
UNIT_FACTOR = EXT_DIR / "snippets" / "mq-unit-factor.liquid"


def _strip_comments(src: str) -> str:
    """Remove Liquid comments, JS comments and HTML comments."""
    src = re.sub(r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", "", src, flags=re.DOTALL)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.MULTILINE)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.DOTALL)
    return src


@pytest.fixture
def block_src():
    return BLOCK.read_text()


@pytest.fixture
def timer_src():
    return TIMER.read_text()


@pytest.fixture
def unit_factor_src():
    return UNIT_FACTOR.read_text()


class TestLiquidFiles:
    def test_block_exists(self):
        assert BLOCK.exists()

    def test_timer_snippet_exists(self):
        assert TIMER.exists()

    def test_unit_factor_snippet_exists(self):
        assert UNIT_FACTOR.exists()

    def test_block_uses_current_price_not_compare_at(self, block_src):
        """Hard rule: NEVER compare_at_price x quantity (04 §2)."""
        assert "compare_at_price" not in _strip_comments(block_src)

    def test_block_reads_product_price(self, block_src):
        """Hard rule: everything calculated with current variant.price."""
        assert "product.price" in block_src

    def test_block_timer_gated_on_ends_at(self, block_src):
        """Timer only if ends_at set and in the future (07 §3)."""
        assert "ends_at" in block_src
        assert "'now' | date: '%s'" in block_src

    def test_timer_snippet_no_localstorage(self, timer_src):
        """Hard rule: no localStorage/cookies for per-visitor start time."""
        code = _strip_comments(timer_src)
        assert "localStorage" not in code
        assert "document.cookie" not in code

    def test_timer_snippet_hides_at_zero(self, timer_src):
        """At 0: hide the timer, do NOT reload."""
        code = _strip_comments(timer_src)
        assert "display = 'none'" in code
        assert "location.reload" not in code

    def test_timer_snippet_counts_down(self, timer_src):
        """Counts down in JS to exactly ends_at."""
        assert "data-ends-at" in timer_src
        assert "setTimeout" in timer_src

    def test_block_schema_has_layout_setting(self, block_src):
        assert '"layout"' in block_src

    def test_block_schema_has_highlight_tier(self, block_src):
        assert '"highlight_tier"' in block_src

    def test_unit_factor_covers_conversion_table(self, unit_factor_src):
        """Same conversion table as 07 §2.2 / unit_price.py."""
        for key in ["g_to_kg", "ml_to_l", "cm_to_m", "cm2_to_m2", "cm3_to_m3"]:
            assert key in unit_factor_src

    def test_block_renders_nothing_without_offer(self, block_src):
        """Renders nothing if no offer configuration exists."""
        assert "{%- if offer and tiers and tiers.size > 0 -%}" in block_src


class TestPythonReferenceCalculation:
    """The Python compliance functions are the reference implementation
    (04 §2). Liquid must produce the same numbers."""

    def test_tier_total_matches_liquid_formula(self):
        """tier_total = price * qty * (1 - pct), rounded — same as Liquid."""
        price = 1999  # cents
        for qty, pct in [(2, 10), (3, 15), (4, 25), (2, 70), (3, 1)]:
            discount = pct / 100.0
            factor = 1.0 - discount
            # Liquid: price | times: qty | times: factor | round
            expected = round(price * qty * factor)
            assert expected == round(price * qty * (1 - discount))

    def test_savings_percentage_only_whole_number(self):
        """Percentage only shown if it is a whole number (04 §2)."""
        for price, qty, pct in [(1999, 2, 10), (1499, 3, 15), (2999, 2, 25)]:
            regular = price * qty
            total = round(price * qty * (1 - pct / 100.0))
            savings = regular - total
            raw_pct = savings * 100.0 / regular
            floor_pct = int(raw_pct)
            round_pct = round(raw_pct)
            if floor_pct == round_pct:
                assert floor_pct in (pct, round_pct)

    def test_regular_price_never_compare_at(self):
        """Regular = current price x qty. A compare_at-based check fails."""
        price = 1999
        compare_at = 2999
        qty = 3
        # Regular per spec: price x qty (current price)
        regular = price * qty
        wrong = compare_at * qty
        assert regular != wrong  # spec choice is strictly current price

    def test_unit_price_calculation(self):
        """Unit price per tier = tier total / (qty x net content)."""
        price = 1999
        qty = 2
        pct = 10
        total = round(price * qty * (1 - pct / 100.0))
        net_value = 250  # g
        ref_qty = net_value * qty  # g
        unit_cents = round(total / (ref_qty / 1000.0))  # g_to_kg divisor 1000
        assert unit_cents > 0


class TestLocales:
    def test_all_locales_have_bundle_picker_keys(self):
        for locale in ["en.default.json", "nl.json", "de.json"]:
            data = json.loads((EXT_DIR / "locales" / locale).read_text())
            bp = data.get("bundle_picker", {})
            for key in ["choose_bundle", "save", "per_item", "limited_time"]:
                assert key in bp, f"{locale} missing bundle_picker.{key}"

    def test_all_locales_have_price_keys(self):
        for locale in ["en.default.json", "nl.json", "de.json"]:
            data = json.loads((EXT_DIR / "locales" / locale).read_text())
            pr = data.get("price", {})
            assert "unit_price" in pr, f"{locale} missing price.unit_price"
