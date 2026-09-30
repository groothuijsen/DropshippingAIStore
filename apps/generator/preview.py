"""Admin preview templates — render section previews for the page editor.

See docs/09-ui-screens.md §page editor.
Each section type has a preview template that shows the structure
without needing a full Shopify storefront render.
"""

from __future__ import annotations

from typing import Any

SECTION_TYPES = [
    "hero",
    "benefits",
    "problem_solution",
    "how_it_works",
    "specs",
    "comparison",
    "faq",
    "guarantee",
    "rich_text",
    "listicle_item",
    "cta",
]


def render_section_preview(section: dict[str, Any]) -> str:
    """Render an HTML preview for a section dict."""
    section_type = section.get("type", "")

    renderer = _RENDERERS.get(section_type)
    if renderer:
        return renderer(section)

    return f'<div class="mq-preview mq-preview--unknown"><em>Unknown section: {section_type}</em></div>'


def render_page_preview(sections: list[dict[str, Any]]) -> str:
    """Render HTML preview for a full page (list of sections)."""
    if not sections:
        return '<div class="mq-preview mq-preview--empty"><em>No sections yet</em></div>'

    previews = []
    for idx, section in enumerate(sections):
        preview = render_section_preview(section)
        previews.append(f'<div class="mq-preview-section" data-index="{idx}">{preview}</div>')

    return '<div class="mq-preview-page">' + "".join(previews) + "</div>"


def _render_hero(s: dict[str, Any]) -> str:
    headline = s.get("headline", "")
    subheadline = s.get("subheadline", "")
    cta = s.get("cta_label", "")
    html = '<div class="mq-preview mq-preview--hero">'
    if headline:
        html += f"<h1>{_esc(headline)}</h1>"
    if subheadline:
        html += f"<p>{_esc(subheadline)}</p>"
    if cta:
        html += f'<button class="mq-btn">{_esc(cta)}</button>'
    html += "</div>"
    return html


def _render_benefits(s: dict[str, Any]) -> str:
    title = s.get("title", "")
    items = s.get("items", [])
    html = '<div class="mq-preview mq-preview--benefits">'
    if title:
        html += f"<h2>{_esc(title)}</h2>"
    html += "<ul>"
    for item in items:
        item_title = item.get("title", "")
        item_text = item.get("text", "")
        html += f"<li><strong>{_esc(item_title)}</strong> — {_esc(item_text)}</li>"
    html += "</ul></div>"
    return html


def _render_problem_solution(s: dict[str, Any]) -> str:
    problem = s.get("problem", "")
    solution = s.get("solution", "")
    return (
        '<div class="mq-preview mq-preview--problem-solution">'
        f"<p><strong>Problem:</strong> {_esc(problem)}</p>"
        f"<p><strong>Solution:</strong> {_esc(solution)}</p>"
        "</div>"
    )


def _render_how_it_works(s: dict[str, Any]) -> str:
    steps = s.get("steps", [])
    html = '<div class="mq-preview mq-preview--how-it-works"><ol>'
    for step in steps:
        title = step.get("title", "")
        text = step.get("text", "")
        html += f"<li><strong>{_esc(title)}</strong> — {_esc(text)}</li>"
    html += "</ol></div>"
    return html


def _render_specs(s: dict[str, Any]) -> str:
    rows = s.get("rows", [])
    html = '<div class="mq-preview mq-preview--specs"><table><tbody>'
    for row in rows:
        label = row.get("label", "")
        value = row.get("value", "")
        html += f"<tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>"
    html += "</tbody></table></div>"
    return html


def _render_comparison(s: dict[str, Any]) -> str:
    ours_label = s.get("ours_label", "Ours")
    other_label = s.get("other_label", "Other")
    rows = s.get("rows", [])
    html = (
        '<div class="mq-preview mq-preview--comparison"><table><thead>'
        f"<tr><th>Feature</th><th>{_esc(ours_label)}</th><th>{_esc(other_label)}</th></tr>"
        "</thead><tbody>"
    )
    for row in rows:
        feature = row.get("feature", "")
        ours = "✓" if row.get("ours") else "✗"
        other = "✓" if row.get("other") else "✗"
        html += f"<tr><td>{_esc(feature)}</td><td>{ours}</td><td>{other}</td></tr>"
    html += "</tbody></table></div>"
    return html


def _render_faq(s: dict[str, Any]) -> str:
    items = s.get("items", [])
    html = '<div class="mq-preview mq-preview--faq">'
    for item in items:
        question = item.get("question", "")
        answer = item.get("answer", "")
        html += f"<details><summary>{_esc(question)}</summary><p>{_esc(answer)}</p></details>"
    html += "</div>"
    return html


def _render_guarantee(s: dict[str, Any]) -> str:
    text = s.get("text", "")
    return f'<div class="mq-preview mq-preview--guarantee"><p>{_esc(text)}</p></div>'


def _render_rich_text(s: dict[str, Any]) -> str:
    title = s.get("title")
    paragraphs = s.get("paragraphs", [])
    html = '<div class="mq-preview mq-preview--rich-text">'
    if title:
        html += f"<h2>{_esc(title)}</h2>"
    for para in paragraphs:
        html += f"<p>{_esc(para)}</p>"
    html += "</div>"
    return html


def _render_listicle_item(s: dict[str, Any]) -> str:
    number = s.get("number", "")
    title = s.get("title", "")
    text = s.get("text", "")
    html = '<div class="mq-preview mq-preview--listicle-item">'
    if number:
        html += f"<span class='num'>{_esc(str(number))}</span> "
    if title:
        html += f"<h3>{_esc(title)}</h3>"
    if text:
        html += f"<p>{_esc(text)}</p>"
    html += "</div>"
    return html


def _render_cta(s: dict[str, Any]) -> str:
    heading = s.get("heading", "")
    text = s.get("text", "")
    button = s.get("button_label", "")
    html = '<div class="mq-preview mq-preview--cta">'
    if heading:
        html += f"<h2>{_esc(heading)}</h2>"
    if text:
        html += f"<p>{_esc(text)}</p>"
    if button:
        html += f'<button class="mq-btn">{_esc(button)}</button>'
    html += "</div>"
    return html


def _esc(text: str) -> str:
    """HTML-escape text."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_RENDERERS = {
    "hero": _render_hero,
    "benefits": _render_benefits,
    "problem_solution": _render_problem_solution,
    "how_it_works": _render_how_it_works,
    "specs": _render_specs,
    "comparison": _render_comparison,
    "faq": _render_faq,
    "guarantee": _render_guarantee,
    "rich_text": _render_rich_text,
    "listicle_item": _render_listicle_item,
    "cta": _render_cta,
}
