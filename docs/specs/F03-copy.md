# F03 — Copy per page type and language

**References:** 05 §3 (`SectionsPayload`), §4.3 (section order); `prompts/copy.md`, `prompts/guardrails.md`; 03 §5.1 (one metaobject entry per language).

## Acceptance criteria

1. **Given** research + chosen angle, **when** step `copy` runs for `pdp`, **then** `SectionsPayload.sections` contains exactly the types in the order the code passed in (05 §4.3: without `specs` when < 2 specs, without `guarantee` when there is no warranty policy). After success a `Page` exists in status `draft`.
2. All fields respect the length limits; exceeding them = schema error (no truncation in code).
3. `specs.rows[].label` matches a key from `ImportResult.specs`; other rows are removed and logged as a warning.
4. Text in `nl`, `en` or `de` according to `content_locale`; a language detection check (`langdetect` or similar) on hero + first paragraph must return the correct language, otherwise one new attempt.
5. The correct niche guardrail block (based on `ResearchResult.niche`) is in the prompt; test by snapshotting the rendered prompt.
6. **Given** the shop has additional published languages (from `shopLocales`, limited to nl/en/de), **when** the merchant chooses "Vertaal" ("Translate") in the editor, **then** Mosaiq runs the `copy` prompt again in that language (same angle, same section order, written natively), stores it in `Page.sections[<lang>]`, runs the compliance check for that language, and publishes a separate metaobject entry with handle suffix `-<lang>` (03 §5.1). Does not count as a store generation.
7. SEO title ≤ 60 and SEO description ≤ 155 characters.

## Assumptions made during build
_(to be filled in by Hermes)_
