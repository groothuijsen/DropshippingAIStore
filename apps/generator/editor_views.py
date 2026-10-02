"""Editor UI for plain-language page edits (F16, T-121).

Routes (09):
- GET/POST ``/app/pages/<page_id>/edit/`` — instruction field (max 500),
  per-section "Ask for a change", locale tabs, diff + Apply/Reject.
- GET ``/app/pages/<page_id>/edit/panel/`` — HTMX fragment (polled while a
  proposal is being generated).
- POST ``/app/pages/<page_id>/edit/<edit_id>/apply|reject/``.
"""

from __future__ import annotations

import copy
import logging
from uuid import UUID

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render

from apps.billing.limits import check_page_edits, consume
from apps.compliance.claims import check_sections
from apps.generator.edit_ops import _get_in, apply_edit
from apps.generator.models import Page, PageEdit
from apps.generator.tasks import generate_page_edit

logger = logging.getLogger(__name__)


def _get_page(page_id) -> Page | None:
    try:
        return Page.objects.get(id=UUID(str(page_id)))
    except (Page.DoesNotExist, ValueError, TypeError):
        return None


def _diff_rows(payload: dict, operations: list[dict]) -> list[dict]:
    """Before/after rows for the merchant-facing diff (F16-3)."""
    sections = list(payload.get("sections") or [])
    rows: list[dict] = []
    for op in operations:
        kind = op.get("op")
        idx = op.get("section_index")
        sec_type = sections[idx].get("type", "?") if isinstance(idx, int) and idx < len(sections) else "?"
        if kind == "replace_field":
            field = op.get("field") or ""
            old, found = _get_in(sections[idx], field) if isinstance(idx, int) and idx < len(sections) else (None, False)
            rows.append({
                "kind": "replace",
                "section": f"{idx + 1} · {sec_type}",
                "field": field,
                "before": old if found else "(not present)",
                "after": op.get("value"),
            })
        elif kind == "add_section":
            new_type = (op.get("section") or {}).get("type", "?")
            rows.append({"kind": "add", "section": f"{idx + 1}", "field": "section", "before": "—", "after": f"+ {new_type}"})
        elif kind == "remove_section":
            rows.append({"kind": "remove", "section": f"{idx + 1}", "field": "section", "before": f"− {sec_type}", "after": "—"})
        elif kind == "move_section":
            rows.append({"kind": "move", "section": f"{idx + 1}", "field": "order", "before": f"position {idx + 1}", "after": f"position {(op.get('to_index') or 0) + 1}"})
    return rows


def _proposed_findings(page: Page, locale: str, operations: list[dict]) -> list[dict]:
    """Claim findings the proposal would introduce (F16-9, highlighted)."""
    payload = copy.deepcopy(page.sections.get(locale) or {})
    sections = list(payload.get("sections") or [])
    for op in operations:
        kind = op.get("op")
        idx = op.get("section_index")
        if not isinstance(idx, int) or idx >= len(sections):
            continue
        if kind == "replace_field" and op.get("field"):
            from apps.generator.edit_ops import _set_in

            _set_in(sections[idx], op["field"], op.get("value"))
        elif kind == "add_section" and op.get("section"):
            sections.insert(min(idx, len(sections)), dict(op["section"]))
        elif kind == "remove_section":
            sections.pop(idx)
        elif kind == "move_section":
            sections.insert(op.get("to_index") or 0, sections.pop(idx))
    return [
        {"rule_id": f.rule_id, "severity": f.severity, "text": f.text}
        for f in check_sections(sections, locale)
    ]


def _latest_edit(page: Page) -> PageEdit | None:
    return page.edits.order_by("-created_at").first()


def page_editor(request: HttpRequest, page_id: str) -> HttpResponse:
    page = _get_page(page_id)
    if page is None:
        return JsonResponse({"error": "Page not found"}, status=404)

    locales = sorted((page.sections or {}).keys())
    locale = request.GET.get("locale") or request.POST.get("locale") or page.content_locale
    if locale not in locales:
        locale = page.content_locale

    limit = check_page_edits(page.shop)
    edit = _latest_edit(page)

    if request.method == "POST":
        action = request.POST.get("action", "propose")

        if action == "propose":
            instruction = (request.POST.get("instruction") or "").strip()
            scope_raw = (request.POST.get("scope") or "").strip()
            scope = int(scope_raw) if scope_raw.isdigit() else None
            other_locales = request.POST.get("other_locales") == "on"

            if not limit.allowed:
                messages.error(
                    request,
                    f"Plan limit reached ({limit.limit} edits per 30 days). The limit resets on {limit.reset_date:%d %B %Y}.",
                )
                return redirect(f"/app/pages/{page.id}/edit/?id_token={request.GET.get("id_token", "")}")

            if not instruction:
                messages.error(request, "Please describe the change you want.")
                return redirect(f"/app/pages/{page.id}/edit/?id_token={request.GET.get("id_token", "")}")

            targets = [locale]
            if other_locales:
                targets += [lc for lc in locales if lc != locale]
            for target in targets:
                generate_page_edit.delay(str(page.id), target, instruction[:500], scope)
            messages.success(request, "Looking for a change — this takes a few seconds.")
            return redirect(f"/app/pages/{page.id}/edit/?locale={locale}&id_token={request.GET.get("id_token", "")}")

    diff_rows = _diff_rows(page.sections.get(locale) or {}, edit.operations) if edit and edit.status == PageEdit.Status.PROPOSED and edit.locale == locale else []
    proposed_findings = _proposed_findings(page, locale, edit.operations) if diff_rows else []
    new_blocks = [f for f in proposed_findings if f["severity"] == "block"]
    current_rules = {f.get("rule_id") for f in (page.compliance_findings or [])}
    fresh_blocks = [f for f in new_blocks if f["rule_id"] not in current_rules]

    raw_sections = (page.sections.get(locale) or {}).get("sections") or []
    section_rows = [
        {"type": sec.get("type", "?"), "preview": sec.get("headline") or sec.get("title") or ""}
        for sec in raw_sections
        if isinstance(sec, dict)
    ]

    return render(
        request,
        "app/page_editor.html",
        {
            "page": page,
            "locales": locales,
            "locale": locale,
            "sections": section_rows,
            "edit": edit,
            "diff_rows": diff_rows,
            "fresh_blocks": fresh_blocks,
            "limit": limit,
            "can_apply": edit is not None and edit.status == PageEdit.Status.PROPOSED and diff_rows,
        },
    )


def editor_panel(request: HttpRequest, page_id: str) -> HttpResponse:
    """HTMX fragment: latest edit block (polled every 3s while proposing)."""
    page = _get_page(page_id)
    if page is None:
        return JsonResponse({"error": "Page not found"}, status=404)
    locale = request.GET.get("locale") or page.content_locale
    edit = _latest_edit(page)
    diff_rows = _diff_rows(page.sections.get(locale) or {}, edit.operations) if edit and edit.status == PageEdit.Status.PROPOSED and edit.locale == locale else []
    return render(request, "app/page_editor_panel.html", {"page": page, "locale": locale, "edit": edit, "diff_rows": diff_rows, "id_token": request.GET.get("id_token", "")})


def apply_edit_view(request: HttpRequest, page_id: str, edit_id: str) -> HttpResponse:
    page = _get_page(page_id)
    if page is None:
        return JsonResponse({"error": "Page not found"}, status=404)
    if request.method != "POST":
        return redirect(f"/app/pages/{page.id}/edit/?id_token={request.GET.get("id_token", "")}")

    edit = page.edits.filter(id=edit_id).first()
    if edit is None or edit.status != PageEdit.Status.PROPOSED:
        messages.error(request, "This edit can no longer be applied.")
        return redirect(f"/app/pages/{page.id}/edit/?id_token={request.GET.get("id_token", "")}")

    try:
        apply_edit(page, edit.locale, edit.operations, edit.base_version)
    except Exception as exc:  # noqa: BLE001 — EditApplyError + EDIT_INVALID
        messages.error(request, str(exc))
        return redirect(f"/app/pages/{page.id}/edit/?id_token={request.GET.get("id_token", "")}")

    edit.status = PageEdit.Status.APPLIED
    edit.save(update_fields=["status", "updated_at"])
    consume(page.shop, "page_edits")
    messages.success(request, "Change applied to the draft.")
    return redirect(f"/app/pages/{page.id}/edit/?locale={edit.locale}&id_token={request.GET.get("id_token", "")}")


def reject_edit_view(request: HttpRequest, page_id: str, edit_id: str) -> HttpResponse:
    page = _get_page(page_id)
    if page is None:
        return JsonResponse({"error": "Page not found"}, status=404)
    if request.method != "POST":
        return redirect(f"/app/pages/{page.id}/edit/?id_token={request.GET.get("id_token", "")}")

    edit = page.edits.filter(id=edit_id).first()
    if edit is None or edit.status != PageEdit.Status.PROPOSED:
        messages.error(request, "This edit is no longer proposed.")
        return redirect(f"/app/pages/{page.id}/edit/?id_token={request.GET.get("id_token", "")}")

    edit.status = PageEdit.Status.REJECTED
    edit.save(update_fields=["status", "updated_at"])
    messages.info(request, "Edit rejected — nothing changed.")
    return redirect(f"/app/pages/{page.id}/edit/?locale={edit.locale}&id_token={request.GET.get("id_token", "")}")
