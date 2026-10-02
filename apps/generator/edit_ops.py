"""Validation + apply engine for plain-language page edits (F16, 12 §3).

`validate_edit_ops` runs the deterministic rules from 12 §3 on the AI's
operations BEFORE the merchant sees them; `apply_edit` applies approved
operations to the draft content, re-runs the claim check (07 §4) and bumps
`Page.version`. Live published content is never touched (F16-6).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from pydantic import TypeAdapter

from apps.ai.schemas import Section

logger = logging.getLogger(__name__)

# Section is an Annotated discriminated union — validate through a TypeAdapter
_section_adapter: TypeAdapter = TypeAdapter(Section)

# 12 §3: no operation may change these (exact names + prefixes)
EDIT_LOCKED_FIELDS = {
    "type",
    "image_slot",
    "price",
    "offer",
    "gpsr",
    "unit_price",
    "prior_price",
}

# 05 §4.3 + the 12 §3 extensions for faq/shipping/returns
PAGE_SECTION_RULES: dict[str, set[str]] = {
    "pdp": {"hero", "benefits", "problem_solution", "how_it_works", "specs", "comparison", "faq", "guarantee", "cta"},
    "landing": {"hero", "problem_solution", "benefits", "how_it_works", "comparison", "faq", "cta"},
    "advertorial": {"rich_text", "cta"},
    "listicle": {"rich_text", "listicle_item", "cta"},
    "home": {"hero", "benefits", "how_it_works", "faq", "cta"},
    "about": {"rich_text"},
    "faq": {"rich_text", "faq"},
    "shipping": {"rich_text", "faq"},
    "returns": {"rich_text", "faq"},
}

# Sections that may never be removed (F16 / 12 §3)
_NEVER_REMOVE = {"hero"}
_MIN_SECTIONS = 2
_MAX_SECTIONS = 14  # SectionsPayload schema bound (05 §3)


class EditApplyError(ValueError):
    """Apply refused — the page changed since the edit was proposed."""


def _is_locked(key: str) -> bool:
    return key in EDIT_LOCKED_FIELDS or any(
        key.startswith(prefix) for prefix in ("price", "offer", "gpsr", "unit_price", "prior_price")
    )


def _get_in(section: dict, path: str) -> tuple[Any, bool]:
    node: Any = section
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None, False
    return node, True


def _set_in(section: dict, path: str, value: Any) -> bool:
    parts = path.split(".")
    node: Any = section
    for part in parts[:-1]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False
    last = parts[-1]
    if isinstance(node, dict) and last in node:
        node[last] = value
        return True
    if isinstance(node, list) and last.isdigit() and int(last) < len(node):
        node[int(last)] = value
        return True
    return False


def validate_edit_ops(
    payload: dict[str, Any],
    page_type: str,
    operations: list[dict[str, Any]],
    scope_section_index: int | None = None,
    guarantee_allowed: bool | None = None,
) -> list[dict[str, str]]:
    """Run the 12 §3 rules. Returns a list of errors; empty = valid."""
    errors: list[dict[str, str]] = []
    sections = list(payload.get("sections") or [])
    allowed_types = PAGE_SECTION_RULES.get(page_type, set())

    if not operations:
        return [{"code": "EDIT_INVALID", "message": "The edit contains no operations."}]

    # Work on a copy so validation never mutates the stored payload
    working = copy.deepcopy(sections)

    for op in operations:
        kind = op.get("op")
        idx = op.get("section_index")
        max_idx = len(working) if kind == "add_section" else max(len(working) - 1, 0)
        if idx is None or not isinstance(idx, int) or idx > max_idx or (kind != "add_section" and idx >= len(working)):
            errors.append({"code": "EDIT_INVALID", "message": f"Section index {idx} out of range."})
            continue

        if kind == "replace_field":
            field = op.get("field") or ""
            root_key = field.split(".")[0] if field else ""
            if not field:
                errors.append({"code": "EDIT_INVALID", "message": "replace_field without a field path."})
                continue
            if _is_locked(root_key):
                errors.append(
                    {"code": "EDIT_LOCKED_FIELDS", "message": f"`{field}` is locked and cannot be edited."}
                )
                continue
            if idx >= len(working) or not isinstance(working[idx], dict):
                errors.append({"code": "EDIT_INVALID", "message": f"Section {idx} does not exist."})
                continue
            _current, found = _get_in(working[idx], field)
            if not found:
                errors.append({"code": "EDIT_INVALID", "message": f"Field `{field}` does not exist in section {idx}."})
                continue
            if not _set_in(working[idx], field, op.get("value")):
                errors.append({"code": "EDIT_INVALID", "message": f"Could not set `{field}`."})
                continue
            # The section model is re-validated after applying (max_length etc.)
            try:
                _section_adapter.validate_python(working[idx])
            except Exception as exc:  # noqa: BLE001 — pydantic ValidationError
                errors.append({"code": "EDIT_INVALID", "message": f"Value does not fit `{field}`: {exc}"})

        elif kind == "add_section":
            section = op.get("section")
            if not isinstance(section, dict):
                errors.append({"code": "EDIT_INVALID", "message": "add_section without a section payload."})
                continue
            try:
                validated = _section_adapter.validate_python(section).model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                errors.append({"code": "EDIT_INVALID", "message": f"Invalid section payload: {exc}"})
                continue
            if validated.get("type") not in allowed_types:
                errors.append(
                    {"code": "EDIT_INVALID", "message": f"Section type `{validated.get('type')}` is not allowed on {page_type} pages."}
                )
                continue
            if validated.get("type") == "guarantee" and guarantee_allowed is False:
                errors.append({"code": "EDIT_INVALID", "message": "No guarantee policy is configured."})
                continue
            if len(working) + 1 > _MAX_SECTIONS:
                errors.append({"code": "EDIT_INVALID", "message": f"A page may not exceed {_MAX_SECTIONS} sections."})
                continue
            working.insert(min(idx, len(working)), validated)

        elif kind == "remove_section":
            if idx >= len(working):
                errors.append({"code": "EDIT_INVALID", "message": f"Section {idx} does not exist."})
                continue
            removed_type = working[idx].get("type") if isinstance(working[idx], dict) else None
            if removed_type in _NEVER_REMOVE and page_type in ("pdp", "home", "landing"):
                errors.append({"code": "EDIT_INVALID", "message": f"A {page_type} page keeps its hero section."})
                continue
            if len(working) - 1 < _MIN_SECTIONS:
                errors.append({"code": "EDIT_INVALID", "message": f"A page keeps at least {_MIN_SECTIONS} sections."})
                continue
            working.pop(idx)

        elif kind == "move_section":
            to_index = op.get("to_index")
            if idx >= len(working) or to_index is None or to_index >= len(working):
                errors.append({"code": "EDIT_INVALID", "message": "move_section with an out-of-range index."})
                continue
            working.insert(to_index, working.pop(idx))

        else:
            errors.append({"code": "EDIT_INVALID", "message": f"Unknown operation `{kind}`."})

    return errors


def apply_edit(page, locale: str, operations: list[dict[str, Any]], base_version: int) -> None:
    """Apply approved operations to the page draft (F16-4).

    Refuses when `Page.version` moved since the edit was proposed. On
    success the deterministic claim check (07 §4) runs again, the compliance
    score is recalculated and the page saves as a new version. Live pages:
    only the local draft changes — the published version stays until the
    merchant re-publishes (F16-6).
    """
    from apps.compliance.claims import check_sections
    from apps.generator.errors import GeneratorError

    page.refresh_from_db()
    if page.version != base_version:
        raise EditApplyError("The page changed; ask again.")

    errors = validate_edit_ops(page.sections.get(locale) or {}, page.page_type, operations)
    if errors:
        raise GeneratorError("EDIT_INVALID", errors[0]["message"])

    payload = dict(page.sections.get(locale) or {})
    sections = copy.deepcopy(list(payload.get("sections") or []))
    payload["sections"] = sections

    # apply on the validated working copy semantics: re-run the same engine
    # path by validating against the fresh payload and then mutating it.
    working_errors = validate_edit_ops(payload, page.page_type, operations)
    if working_errors:
        raise GeneratorError("EDIT_INVALID", working_errors[0]["message"])

    # Mutation pass (validation above proved every op is safe)
    for op in operations:
        kind = op["op"]
        idx = op["section_index"]
        if kind == "replace_field":
            _set_in(sections[idx], op["field"], op.get("value"))
        elif kind == "add_section":
            sections.insert(min(idx, len(sections)), _section_adapter.validate_python(op["section"]).model_dump(mode="json"))
        elif kind == "remove_section":
            sections.pop(idx)
        elif kind == "move_section":
            sections.insert(op["to_index"], sections.pop(idx))

    new_sections = dict(page.sections)
    new_sections[locale] = payload
    findings = check_sections(sections, locale)
    page.sections = new_sections
    page.compliance_findings = [
        {"rule_id": f.rule_id, "severity": f.severity, "field_path": f.field_path, "text": f.text}
        for f in findings
    ]
    block_count = sum(1 for f in findings if f.severity == "block")
    warn_count = sum(1 for f in findings if f.severity == "warn")
    page.compliance_score = max(0, 100 - block_count * 25 - warn_count * 5)
    page.version += 1
    page.save(update_fields=["sections", "compliance_findings", "compliance_score", "version", "updated_at"])
