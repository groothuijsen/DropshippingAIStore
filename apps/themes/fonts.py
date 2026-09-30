"""Bundled OFL fonts for the mq-tokens embed.

See docs/04-extensions.md §1.
6 open-license fonts (OFL), Latin subset, 2 weights, woff2, ≤ 600 KB combined.
No Google Fonts CDN (legally risky in Germany). No font_picker in app extensions.
"""

BUNDLED_FONTS: dict[str, dict[str, str]] = {
    "inter": {
        "name": "Inter",
        "weights": "400, 600",
        "license": "OFL-1.1",
        "css_family": "'Inter', sans-serif",
    },
    "manrope": {
        "name": "Manrope",
        "weights": "400, 700",
        "license": "OFL-1.1",
        "css_family": "'Manrope', sans-serif",
    },
    "source-sans-3": {
        "name": "Source Sans 3",
        "weights": "400, 600",
        "license": "OFL-1.1",
        "css_family": "'Source Sans 3', sans-serif",
    },
    "nunito": {
        "name": "Nunito",
        "weights": "400, 700",
        "license": "OFL-1.1",
        "css_family": "'Nunito', sans-serif",
    },
    "work-sans": {
        "name": "Work Sans",
        "weights": "400, 600",
        "license": "OFL-1.1",
        "css_family": "'Work Sans', sans-serif",
    },
    "lora": {
        "name": "Lora",
        "weights": "400, 600",
        "license": "OFL-1.1",
        "css_family": "'Lora', serif",
    },
}

THEME_FONT_KEY = "theme"  # "Font van mijn thema" — inherit the theme font


def get_font_keys() -> list[str]:
    """Get list of valid font keys (including 'theme' for inherit)."""
    return list(BUNDLED_FONTS.keys()) + [THEME_FONT_KEY]


def is_valid_font(key: str) -> bool:
    """Check if a font key is valid."""
    return key in BUNDLED_FONTS or key == THEME_FONT_KEY


def get_font_css(key: str) -> str:
    """Get CSS font-family value for a font key."""
    if key == THEME_FONT_KEY or not key:
        return "inherit"
    font = BUNDLED_FONTS.get(key)
    if font:
        return font["css_family"]
    return "inherit"
