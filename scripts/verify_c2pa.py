#!/usr/bin/env python3
"""Verify C2PA on Shopify CDN — T-043.

Checks whether the C2PA manifest survives on:
1. The original file in Shopify Files
2. Transformed variants (?width=800&format=webp)

Usage:
    python scripts/verify_c2pa.py <file_url_or_path> [--variant "width=800&format=webp"]

Requires c2patool and exiftool installed:
    brew install c2pa exiftool
    # or: pip install c2pa-cli

Results update docs/07-compliance.md §6 (Q3).
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def check_c2patool(path: str) -> dict:
    """Run c2patool on a file. Returns manifest info."""
    try:
        result = subprocess.run(
            ["c2patool", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        has_manifest = "Manifest" in output or "manifest found" in output.lower() or "c2pa manifest" in output.lower()
        return {
            "tool": "c2patool",
            "has_manifest": has_manifest,
            "output": output[:2000],
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {"tool": "c2patool", "has_manifest": None, "error": "c2patool not installed"}
    except subprocess.TimeoutExpired:
        return {"tool": "c2patool", "has_manifest": None, "error": "Timeout"}


def check_exiftool(path: str) -> dict:
    """Run exiftool on a file. Returns C2PA-related metadata."""
    try:
        result = subprocess.run(
            ["exiftool", "-a", "-u", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        has_c2pa = "c2pa" in output.lower() or "C2PA" in output
        has_manifest = "Manifest" in output
        return {
            "tool": "exiftool",
            "has_c2pa": has_c2pa,
            "has_manifest": has_manifest,
            "output": output[:2000],
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {"tool": "exiftool", "has_c2pa": None, "error": "exiftool not installed"}
    except subprocess.TimeoutExpired:
        return {"tool": "exiftool", "has_c2pa": None, "error": "Timeout"}


def verify_file(path_or_url: str, variant: str = "") -> dict:
    """Verify C2PA on a file (local path or URL).

    Args:
        path_or_url: Local file path or Shopify CDN URL
        variant: Optional query string for CDN variant (e.g. "width=800&format=webp")

    Returns:
        Verification results dict
    """
    import tempfile

    import httpx

    target = path_or_url
    is_remote = path_or_url.startswith("http")
    original_url = path_or_url

    if is_remote and variant:
        separator = "&" if "?" in path_or_url else "?"
        target = f"{path_or_url}{separator}{variant}"
        original_url = target

    # Download if remote
    local_path = None
    if is_remote:
        try:
            resp = httpx.get(target, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as f:
                f.write(resp.content)
                local_path = f.name
            target = local_path
        except Exception as e:
            return {"url": target, "error": str(e)}

    try:
        c2pa_result = check_c2patool(target)
        exiftool_result = check_exiftool(target)

        has_manifest = (
            c2pa_result.get("has_manifest") or exiftool_result.get("has_c2pa") or exiftool_result.get("has_manifest")
        )

        return {
            "url": original_url,
            "variant": variant,
            "has_manifest": bool(has_manifest),
            "c2patool": c2pa_result,
            "exiftool": exiftool_result,
        }
    finally:
        if local_path:
            Path(local_path).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify C2PA on Shopify CDN")
    parser.add_argument("file", help="File URL or local path")
    parser.add_argument("--variant", default="", help="CDN variant query (e.g. width=800&format=webp)")
    args = parser.parse_args()

    result = verify_file(args.file, args.variant)

    print(f"URL: {result.get('url', 'N/A')}")
    print(f"Variant: {result.get('variant', 'original')}")
    print(f"Has manifest: {result.get('has_manifest', 'UNKNOWN')}")
    print(f"C2PATool: {result.get('c2patool', {})}")
    print(f"ExifTool: {result.get('exiftool', {})}")

    if result.get("has_manifest"):
        print("\n✅ C2PA manifest PRESENT")
    else:
        print("\n⚠️  C2PA manifest NOT FOUND (may be stripped by CDN)")


if __name__ == "__main__":
    main()
