# F01 — Product import

**References:** 05 §4.1, 06 (complete), 02 (`ProductSource`), 03 §5 (`product_get`, `products_list`, `product_create_manual`).

## Goal
The merchant chooses the source of a generation: existing Shopify product (preferred), manual input or a public URL (facts only). Mosaiq determines the source app and respects locked fields.

## Acceptance criteria

1. **Given** a shop with products, **when** the merchant chooses "Bestaand product" ("Existing product"), **then** they see a paginated list (50 per page, search field on title) with a source label per product.
2. **Given** a product imported via a sync app or of unknown origin, **then** `ProductSource.source` ≠ `manual` and `locked_fields` contains all fields from 06 §3 except `templateSuffix` and `$app:mosaiq`.
3. **Given** a locked product, **when** code attempts to change `title`, price, variants, media, tags or description, **then** `LockedFieldError` and no HTTP call.
4. **Given** manual input with a valid `ManualProduct`, **when** saved, **then** `productSet` creates the product (status `DRAFT`), `ProductSource.source = manual`, `created_by_mosaiq = True`, `detected_by = mosaiq`, and the product is fully editable by Mosaiq.
5. **Given** a public URL that can be fetched, **then** the job returns `needs_input` with a prefilled `ManualProduct` form (title, description from facts, specs); no text or image from the source is copied verbatim. After confirmation (with price and at least one own photo) a manual product is created and the job continues.
6. **Given** a URL that returns 403/404/captcha/timeout or a `robots.txt` that disallows us, **then** job step `failed` with `IMPORT_SOURCE_BLOCKED` and the UI shows the manual form, prefilled with the URL.
7. **Given** an existing product without own media, **then** step `images` later becomes `skipped` with the message from 05 §4.1.
8. **Given** the onboarding answers and `SOURCE_RULES`, **then** the code detects the source for the test fixtures of every verified app (06 §4.3).
9. On the first generation with media from a sync app, the merchant confirms the right to use those images; stored in `AuditLog`.

## Out of scope
Supplier integrations, pricing rules, product research.

## Assumptions made during build
_(to be filled in by Hermes)_
