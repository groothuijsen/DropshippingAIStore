"""Markdown content loader for the marketing site (13 §4, D-19.2).

Copy lives in ``content/marketing/<lang>/<page>.md`` with YAML front matter.
"""

from __future__ import annotations

import pathlib

CONTENT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / "content" / "marketing"

LANGUAGES = ("en", "nl")


def _parse(raw: str) -> tuple[dict, str]:
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end > 0:
            import yaml

            meta = yaml.safe_load(raw[3:end]) or {}
            body = raw[end + 4 :].strip()
            return meta, body
    return {}, raw.strip()


def load_page(lang: str, slug: str) -> dict:
    """Load one content page. Raises FileNotFoundError when missing."""
    path = CONTENT_ROOT / lang / f"{slug}.md"
    if not path.exists():
        raise FileNotFoundError(f"marketing content not found: {lang}/{slug}.md")
    meta, body = _parse(path.read_text(encoding="utf-8"))
    return {
        "lang": lang,
        "slug": meta.get("slug", f"/{slug}/" if slug != "home" else "/"),
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "template": meta.get("template", "marketing/page_default.html"),
        "sections": meta.get("sections") or [],
        "body": body,
        "source_file": str(path),
    }


def list_pages(lang: str) -> list[str]:
    directory = CONTENT_ROOT / lang
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))
