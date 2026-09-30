"""Palette validation — hex codes + WCAG contrast ratio.

See F05 criterion 3: hex codes valid; contrast text on background ≥ 4.5:1.
"""

from __future__ import annotations

import re
from typing import Any

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

PALETTE_KEYS = ["primary", "secondary", "accent", "background", "text"]


def is_valid_hex(color: str) -> bool:
    """Check if a string is a valid 6-digit hex color."""
    return bool(HEX_PATTERN.match(color))


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert #RRGGBB to (R, G, B) tuple."""
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def _srgb_to_linear(c: float) -> float:
    """Convert sRGB component to linear."""
    c = c / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Calculate relative luminance per WCAG 2.1."""
    r, g, b = hex_to_rgb(hex_color)
    r_lin = _srgb_to_linear(r)
    g_lin = _srgb_to_linear(g)
    b_lin = _srgb_to_linear(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def contrast_ratio(color1: str, color2: str) -> float:
    """Calculate contrast ratio between two hex colors (WCAG 2.1)."""
    lum1 = relative_luminance(color1)
    lum2 = relative_luminance(color2)
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def validate_palette(palette: dict[str, str]) -> dict[str, Any]:
    """Validate a palette dict. Returns {valid: bool, errors: list[str], suggestions: dict}.

    Checks:
    1. All required keys present
    2. All hex codes valid
    3. text on background contrast ≥ 4.5:1
    """
    errors: list[str] = []
    suggestions: dict[str, str] = {}

    # Check required keys
    for key in PALETTE_KEYS:
        if key not in palette:
            errors.append(f"Missing palette key: {key}")
            return {"valid": False, "errors": errors, "suggestions": suggestions}

    # Check hex validity
    for key in PALETTE_KEYS:
        if not is_valid_hex(palette[key]):
            errors.append(f"Invalid hex color for {key}: {palette[key]} (expected #RRGGBB)")

    if errors:
        return {"valid": False, "errors": errors, "suggestions": suggestions}

    # Check contrast: text on background ≥ 4.5:1
    ratio = contrast_ratio(palette["text"], palette["background"])
    if ratio < 4.5:
        errors.append(f"Contrast too low: text on background is {ratio:.2f}:1 (minimum 4.5:1)")
        # Suggest a darker text color
        suggestions["text"] = _suggest_darker_text(palette["text"], palette["background"])
        return {"valid": False, "errors": errors, "suggestions": suggestions}

    return {"valid": True, "errors": [], "suggestions": {}}


def _suggest_darker_text(current_text: str, background: str) -> str:
    """Suggest a darker text color that meets 4.5:1 contrast."""
    r, g, b = hex_to_rgb(current_text)

    # Darken the text color until contrast is sufficient
    for factor in range(90, 0, -5):
        new_r = int(r * factor / 100)
        new_g = int(g * factor / 100)
        new_b = int(b * factor / 100)
        candidate = f"#{new_r:02X}{new_g:02X}{new_b:02X}"
        if contrast_ratio(candidate, background) >= 4.5:
            return candidate

    # Fall back to black
    return "#000000"
