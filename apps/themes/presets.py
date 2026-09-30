"""Style presets — radius, spacing, button style, heading style per preset.

See docs/05-ai-pipeline.md §3.3, docs/08-billing.md, F05 criterion 6.
Presets are data, not code. Two stores with different presets look visibly different.
"""

from typing import Any

STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "clean": {
        "radius": {"base": "8px", "button": "6px", "card": "10px"},
        "spacing": {"scale": 1.0, "section_padding": "48px"},
        "button": {"style": "solid", "text_transform": "none", "font_weight": "500"},
        "heading": {"font_weight": "600", "letter_spacing": "-0.01em", "text_transform": "none"},
    },
    "bold": {
        "radius": {"base": "4px", "button": "4px", "card": "6px"},
        "spacing": {"scale": 0.9, "section_padding": "40px"},
        "button": {"style": "solid", "text_transform": "uppercase", "font_weight": "700"},
        "heading": {"font_weight": "800", "letter_spacing": "-0.02em", "text_transform": "uppercase"},
    },
    "organic": {
        "radius": {"base": "16px", "button": "24px", "card": "20px"},
        "spacing": {"scale": 1.2, "section_padding": "64px"},
        "button": {"style": "solid", "text_transform": "none", "font_weight": "500"},
        "heading": {"font_weight": "500", "letter_spacing": "0em", "text_transform": "none"},
    },
    "luxe": {
        "radius": {"base": "2px", "button": "0px", "card": "2px"},
        "spacing": {"scale": 1.3, "section_padding": "72px"},
        "button": {"style": "outline", "text_transform": "uppercase", "font_weight": "600"},
        "heading": {"font_weight": "300", "letter_spacing": "0.08em", "text_transform": "uppercase"},
    },
    "tech": {
        "radius": {"base": "6px", "button": "4px", "card": "8px"},
        "spacing": {"scale": 0.85, "section_padding": "36px"},
        "button": {"style": "solid", "text_transform": "uppercase", "font_weight": "600"},
        "heading": {"font_weight": "700", "letter_spacing": "-0.02em", "text_transform": "none"},
    },
    "soft": {
        "radius": {"base": "20px", "button": "30px", "card": "24px"},
        "spacing": {"scale": 1.15, "section_padding": "56px"},
        "button": {"style": "solid", "text_transform": "none", "font_weight": "500"},
        "heading": {"font_weight": "500", "letter_spacing": "0em", "text_transform": "none"},
    },
}


def get_preset(name: str) -> dict[str, Any]:
    """Get preset data by name. Defaults to 'clean' for unknown presets."""
    return STYLE_PRESETS.get(name, STYLE_PRESETS["clean"])


def get_preset_names() -> list[str]:
    """Get list of valid preset names."""
    return list(STYLE_PRESETS.keys())
