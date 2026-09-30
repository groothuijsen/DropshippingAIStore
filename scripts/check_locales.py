#!/usr/bin/env python3
"""Check that all locale files have the same keys.

See docs/specs/F06-theme-extension.md criterion 4.
A missing key = CI error.
"""

import json
import sys
from pathlib import Path


def get_nested_keys(obj: dict, prefix: str = "") -> set[str]:
    """Get all nested keys from a dict, dot-separated."""
    keys = set()
    for key, value in obj.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys.update(get_nested_keys(value, full_key))
        else:
            keys.add(full_key)
    return keys


def main() -> int:
    locales_dir = Path(__file__).parent.parent / "extensions" / "theme-blocks" / "locales"

    if not locales_dir.exists():
        print(f"ERROR: Locales directory not found: {locales_dir}")
        return 1

    # Find all locale files
    locale_files = sorted(locales_dir.glob("*.json"))
    if not locale_files:
        print(f"ERROR: No locale files found in {locales_dir}")
        return 1

    # Load reference locale (en.default.json)
    reference_file = locales_dir / "en.default.json"
    if not reference_file.exists():
        print(f"ERROR: Reference locale file not found: {reference_file}")
        return 1

    with open(reference_file) as f:
        reference = json.load(f)

    reference_keys = get_nested_keys(reference)
    print(f"Reference: {reference_file.name} ({len(reference_keys)} keys)")

    # Check each locale file
    errors = []
    for locale_file in locale_files:
        if locale_file == reference_file:
            continue

        with open(locale_file) as f:
            locale_data = json.load(f)

        locale_keys = get_nested_keys(locale_data)

        missing = reference_keys - locale_keys
        extra = locale_keys - reference_keys

        if missing:
            errors.append(f"{locale_file.name}: missing keys: {sorted(missing)}")
        if extra:
            errors.append(f"{locale_file.name}: extra keys: {sorted(extra)}")

        print(f"  {locale_file.name}: {len(locale_keys)} keys", end="")
        if missing:
            print(f" MISSING: {sorted(missing)}", end="")
        if extra:
            print(f" EXTRA: {sorted(extra)}", end="")
        print()

    if errors:
        print("\nERROR: Locale files are out of sync:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("\nAll locale files are in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
