"""Tests for T-033: mq-page-sections section types + admin preview templates."""

from pathlib import Path

from apps.generator.preview import (
    SECTION_TYPES,
    render_page_preview,
    render_section_preview,
)

EXTENSIONS_DIR = Path(__file__).parent.parent / "extensions" / "theme-blocks"
BLOCK_FILE = EXTENSIONS_DIR / "blocks" / "mq-page-sections.liquid"


# ── Liquid block tests ────────────────────────────────────────────────────


class TestMqPageSectionsLiquid:
    def test_block_exists(self):
        assert BLOCK_FILE.exists()

    def test_all_section_types_in_liquid(self):
        """All 11 section types must be handled in the Liquid template."""
        content = BLOCK_FILE.read_text()
        for stype in SECTION_TYPES:
            assert f"'{stype}'" in content, f"Section type '{stype}' not in Liquid template"

    def test_uses_app_namespace(self):
        content = BLOCK_FILE.read_text()
        assert "$app:mosaiq" in content

    def test_renders_nothing_if_missing(self):
        content = BLOCK_FILE.read_text()
        assert "{%- if page_metafield" in content

    def test_accessible_faq_details(self):
        """FAQ uses <details> (F06 criterion 7)."""
        content = BLOCK_FILE.read_text()
        assert "<details" in content
        assert "<summary" in content

    def test_accessible_heading_hierarchy(self):
        """Hero uses h1, sections use h2 (F06 criterion 7)."""
        content = BLOCK_FILE.read_text()
        assert "<h1" in content  # hero headline
        assert "<h2" in content  # section titles

    def test_comparison_uses_table(self):
        content = BLOCK_FILE.read_text()
        assert "<table" in content
        assert 'scope="col"' in content

    def test_specs_uses_table(self):
        content = BLOCK_FILE.read_text()
        assert 'scope="row"' in content


# ── Preview template tests ────────────────────────────────────────────────


class TestPreviewTemplates:
    def test_all_section_types_have_renderers(self):
        """Every section type must have a preview renderer."""
        for stype in SECTION_TYPES:
            section = {"type": stype}
            result = render_section_preview(section)
            css_class = stype.replace("_", "-")
            assert f"mq-preview--{css_class}" in result, f"No renderer for '{stype}'"

    def test_hero_preview(self):
        result = render_section_preview(
            {
                "type": "hero",
                "headline": "Great Product",
                "subheadline": "The best thing ever",
                "cta_label": "Buy Now",
            }
        )
        assert "Great Product" in result
        assert "Buy Now" in result

    def test_benefits_preview(self):
        result = render_section_preview(
            {
                "type": "benefits",
                "title": "Why Choose Us",
                "items": [
                    {"title": "Fast", "text": "Lightning fast"},
                    {"title": "Cheap", "text": "Best price"},
                ],
            }
        )
        assert "Why Choose Us" in result
        assert "Lightning fast" in result

    def test_comparison_preview(self):
        result = render_section_preview(
            {
                "type": "comparison",
                "ours_label": "Ours",
                "other_label": "Other",
                "rows": [
                    {"feature": "Speed", "ours": True, "other": False},
                    {"feature": "Price", "ours": True, "other": True},
                ],
            }
        )
        assert "Ours" in result
        assert "Speed" in result
        assert "✓" in result
        assert "✗" in result

    def test_faq_preview(self):
        result = render_section_preview(
            {
                "type": "faq",
                "items": [
                    {"question": "What is this?", "answer": "A product"},
                    {"question": "How much?", "answer": "€29.99"},
                ],
            }
        )
        assert "<details>" in result
        assert "What is this?" in result

    def test_specs_preview(self):
        result = render_section_preview(
            {
                "type": "specs",
                "rows": [
                    {"label": "Material", "value": "Cotton"},
                    {"label": "Size", "value": "M"},
                ],
            }
        )
        assert "Material" in result
        assert "Cotton" in result

    def test_unknown_section_type(self):
        result = render_section_preview({"type": "nonexistent"})
        assert "Unknown section" in result

    def test_html_escaping(self):
        result = render_section_preview(
            {
                "type": "hero",
                "headline": "<script>alert('xss')</script>",
            }
        )
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_page_preview_empty(self):
        result = render_page_preview([])
        assert "No sections yet" in result

    def test_page_preview_multiple_sections(self):
        result = render_page_preview(
            [
                {"type": "hero", "headline": "Hello"},
                {"type": "benefits", "title": "Why", "items": [{"title": "A", "text": "B"}]},
            ]
        )
        assert "mq-preview-page" in result
        assert "Hello" in result
        assert "mq-preview--benefits" in result
