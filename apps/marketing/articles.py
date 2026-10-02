"""Loader for blog posts and help articles (T-157).

Content lives in content/marketing/en/<section>/<slug>.md with YAML
front matter (title, date, draft). Dutch mirrors in nl/ when present.
"""

from __future__ import annotations

import pathlib

from .content import CONTENT_ROOT, _parse


def _dir(lang: str, section: str) -> pathlib.Path:
    return CONTENT_ROOT / lang / section


def list_articles(lang: str, section: str, include_drafts: bool = False) -> list[dict]:
    posts: list[dict] = []
    directory = _dir(lang, section)
    if not directory.exists():
        return posts
    for path in sorted(directory.glob('*.md'), reverse=True):
        meta, body = _parse(path.read_text(encoding='utf-8'))
        if meta.get('draft') and not include_drafts:
            continue
        posts.append({
            'slug': path.stem,
            'title': meta.get('title', path.stem),
            'description': meta.get('description', ''),
            'date': str(meta.get('date', '')),
            'draft': bool(meta.get('draft')),
            'body': body,
        })
    if include_drafts:
        posts.sort(key=lambda p: p['date'], reverse=True)
    return posts


def get_article(lang: str, section: str, slug: str, include_drafts: bool = False) -> dict | None:
    for post in list_articles(lang, section, include_drafts=True):
        if post['slug'] == slug and (include_drafts or not post['draft']):
            return post
    return None
