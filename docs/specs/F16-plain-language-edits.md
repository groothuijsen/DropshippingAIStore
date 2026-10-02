# F16 — Page edits in plain language

**References:** 12 §2.5, §3 (`PageEditResult`, validation rules), §5, §6, §7; F07 (editor, versions), 07 §4 (claim check), 05 §4.3 (section rules).

The merchant types an instruction ("make the hero more premium", "add a FAQ about shipping", "shorter benefits") for the whole page or one section. Mosaiq proposes operations, shows a diff, and applies them only after approval.

## Acceptance criteria

1. The page editor shows an instruction field (max 500 characters) for the whole page and an "Ask for a change" button per section.
2. **When** an instruction is sent, **then** one AI call (`edit_page.md`) with the current `SectionsPayload` for that locale, the BrandKit tone, the research result and the guardrails returns a `PageEditResult`. The result is validated by schema and by the code rules in 12 §3. Invalid → `PageEdit.status = failed`, code `EDIT_INVALID`, a merchant message, nothing changed, and the edit does not count towards the limit.
3. **Diff.** A valid result is shown as a before/after per affected field or section, plus the AI's `summary`. The merchant chooses Apply or Reject.
4. **Apply.** Applying is refused when `Page.version` changed since the edit was proposed (`base_version` mismatch) with the message "The page changed; ask again". On success: the operations are applied to the draft content, the deterministic claim check (07 §4) runs again, the compliance score is recalculated, the page saves as a new version, and the edit counts towards `page_edits`.
5. **Locked fields.** No operation can change prices, offers, GPSR data, unit prices, prior prices, image slots or section types (`EDIT_LOCKED_FIELDS`). Test with instructions that ask for exactly that ("set the price to €19", "remove the safety information"): the result is `failed` or contains no such operation.
6. **Live pages.** Edits on a live page change the draft only; the live version stays until the merchant re-publishes (F07-5).
7. **Locales.** An edit applies to one locale. The UI offers "Apply to other languages too", which creates one edit per other locale (separate AI call each, each counted).
8. **Limits.** The `page_edits` counter is checked before the AI call (12 §7). Over the limit: the field is disabled with the reset date.
9. **Guardrails.** The same guardrails as `copy` apply (`docs/prompts/guardrails.md`, niche claim rules). A result that introduces a blocked claim is shown with the claim finding highlighted; Apply stays possible, but go-live stays blocked as usual.

## Assumptions made during build

1. **Counter consumed on apply** (T-120): `page_edits` is checked before the AI call but incremented only when the merchant applies — EDIT_INVALID and rejected proposals never count (F16-2/4 read together).
2. **`guarantee` add without a shop check**: the validator allows adding a `guarantee` section; the copy-time condition (Shop.guarantee_policy filled, 05 §4.3) still governs initial builds. `guarantee_allowed=None` skips the check; pass `False` to block.
3. **`PageEdit.ai_call` stays null for now**: `call_ai` logs its own AiCall row but does not return the id; linking is a follow-up when the editor UI (T-121) needs cost display.
4. **Facts context**: the edit prompt receives the import-step facts of the page's job when present, otherwise an empty list; BrandKit tone falls back to "friendly, direct".
