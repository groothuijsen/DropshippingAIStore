# F08 — Saving and reusing templates

**References:** 02 (`SavedTemplate`), 09 (`save-template`).

## Acceptance criteria

1. **When** the merchant saves a page as a template, **then** `SavedTemplate.structure` contains the page type, the section order, per section the type and the display settings, and **no** product text, prices, images or claims.
2. **Given** a template, **when** the merchant starts a new generation with that template, **then** step `copy` uses the section order from the template instead of the default order (05 §4.3); all other rules apply.
3. A template with a section type that does not exist (anymore) is rejected with a clear message.
4. MVP: templates only within the same shop. `shared_with_account` is present but hidden in the UI.

## Assumptions made during build
_(to be filled in by Hermes)_
