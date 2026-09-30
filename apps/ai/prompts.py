"""Prompt rendering — loads prompt templates and renders with Django templating.

See docs/05-ai-pipeline.md §2.1.
Prompts live in docs/prompts/<step>.md. Never use f-strings for prompts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.template import Context, Template

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "prompts"


def load_prompt(step_name: str) -> str:
    """Load a prompt template from docs/prompts/<step_name>.md.

    Strips the YAML-like header (first section before the first '---').
    """
    prompt_file = PROMPTS_DIR / f"{step_name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_file}")

    content = prompt_file.read_text(encoding="utf-8")

    # Strip the header (everything before the first ---)
    parts = content.split("---", 1)
    if len(parts) == 2:
        content = parts[1].strip()

    return content


def render_prompt(step_name: str, variables: dict[str, Any]) -> tuple[str, str]:
    """Render a prompt template with variables.

    Returns (system_prompt, user_prompt) split on the '## User' heading.

    If the template has no '## User' section, the entire rendered content
    is returned as the system prompt with an empty user prompt.
    """
    raw = load_prompt(step_name)
    template = Template(raw)
    rendered = template.render(Context(variables))

    # Split on '## User' if present
    if "## User" in rendered:
        parts = rendered.split("## User", 1)
        system = parts[0].strip()
        user = parts[1].strip() if len(parts) > 1 else ""
    else:
        system = rendered.strip()
        user = ""

    return system, user
