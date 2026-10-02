# F15 — Start from zero (niche-first store builder)

**References:** 12 §1 (D-15.1–D-15.5), §2.1–2.3, §2.7, §3, §4, §5, §6, §7, §8; F05 (BrandKit), F07 (pages, go-live), F01/06 (import and ownership), 09 (onboarding).

Second onboarding route: the merchant describes a niche and Mosaiq proposes a brand name, brand kit, product ideas and a store structure, then builds collections, standard pages, a homepage, product pages and a menu. Products are imported by the merchant's own import app (D-15.2).

## Acceptance criteria

1. **Route choice.** **Given** onboarding step `brand`, **then** the merchant first chooses "I already have a brand and products" (existing F05 flow, unchanged) or "Start from zero". The choice is stored in `Shop.onboarding_route`. **When** "Start from zero" is chosen, **then** the merchant is sent to `/app/start/` and a `StoreBlueprint` with status `brief` is created. The other onboarding steps (`sources`, `theme`, `withdrawal`) still run after the wizard.
2. **Scopes.** **Given** the shop lacks `write_online_store_navigation` or `write_publications`, **then** the wizard shows an explanation and a button to grant them, and no build can start (`SCOPE_MISSING`).
3. **Brief.** Description 20–500 characters, 1–5 markets, 1–3 content locales, audience, price level, import app. Invalid input shows field errors; nothing is sent to the AI until valid.
4. **Names.** **When** the brief is saved, **then** one AI call (`niche_names.md`) returns exactly 8 names that pass `NameSuggestions` validation, the 07 §4.1 blocklist and `themes/brand_blocklist.py`; names that fail are dropped and the call is repeated once for the missing count. Each name shows a .com indication (`likely_free` / `taken` / `unknown`, RDAP) and a link to a TMview search for that name, with the text "Not a trademark check — check before you commit". The merchant can regenerate (max 3 times per blueprint) or type an own name (same blocklist check).
5. **Brand.** **When** a name is chosen, **then** one AI call (`niche_brand.md`) returns a `BrandProposal`; the existing BrandKit form opens pre-filled (name, tone, preset, palette, fonts, tagline). F05 validation applies (contrast ≥ 4.5:1, font keys from the bundled list). Saving writes the BrandKit and design tokens exactly as F05-5.
6. **Product ideas.** **When** the brand is saved, **then** one AI call (`product_ideas.md`) returns 5–10 ideas with search phrases, price band and EU notes, plus an "avoid" list. The screen shows a deep link to the chosen import app (06 §4 app list) and sets `started_products_at`.
7. **Import waiting.** The screen lists products created in the shop after `started_products_at` (from `products/create` webhooks and a fallback products query every 10 s while the page is open). Source detection (06) runs on them as usual. The merchant selects 1–20 products (plan maximum, 12 §7). With 0 selected, "Next" is disabled (`BLUEPRINT_NO_PRODUCTS`). Existing products in the shop may also be selected.
8. **Structure.** **When** products are selected, **then** one AI call (`store_structure.md`) returns a `StoreStructure`. Every `product_gids` entry must be in the selection (else repair once, then fail with a merchant message). The merchant can rename, add, remove and reorder collections, menu items and pages before building.
9. **Business details.** **Given** pages `returns` or the contact page are in the structure and `BusinessDetails.is_complete("returns"/"contact")` is not empty, **then** the build may start, but those pages stay draft with the missing fields listed, and their go-live is blocked (`BUSINESS_DETAILS_MISSING`).
10. **Build.** **When** "Build my store" is clicked, **then** limits are reserved per 12 §7 in one transaction; a `store_build` job runs per 12 §5: collections created unpublished, page jobs for home + standard pages, PDP jobs per product, menu `mosaiq-main` created last. Every created Shopify resource is stored as `ManagedResource`. Nothing touches `main-menu`, theme files, shop policies, or fields that 06 marks as owned by a sync app.
11. **Status.** The status screen shows each item (collection, page, PDP, menu) with its state and a "Retry" for failed items. A failed PDP does not stop the others.
12. **Menu placement.** After the build, a step explains how to select the `mosaiq-main` menu in the theme header, with a theme-editor deep link and a "Done" checkbox (same pattern as 09 onboarding `theme`).
13. **Go-live.** All pages are created as drafts (F07). "Publish store" runs F07 go-live for every page whose preconditions are met (compliance, GPSR, unit price, business details) and publishes the collections (`publishablePublish`). Pages that fail preconditions are listed with the reason; the rest go live.
14. **Undo.** "Undo store build" deletes collections, the `mosaiq-main` menu and the non-live pages created by this blueprint (12 §2.3). Live pages are listed and must be archived first. Products and the BrandKit stay. Every deletion is logged in `AuditLog`.
15. **Idempotency.** Re-running a failed build step does not create duplicates: collections and pages are looked up via `ManagedResource` first; the menu is updated if `mosaiq-main` exists.
16. **No invented facts.** No generated page contains an address, registration number, phone number, delivery time, shipping cost or return address that does not come from `BusinessDetails` or `DeliveryProfile`. Test: generate with empty business details and profiles, then search the output for digits and postal-code patterns outside the inserted blocks; none may appear.

## Tests (minimum)
- Fixtures for every new GraphQL operation (12 §4), recorded from the dev store.
- Blueprint state machine: each status only advances in order; back navigation keeps data.
- Name blocklist: "EcoGlow", "Nike", "SwissSleep" are rejected; RDAP failure → `unknown`, not an error.
- Build with 3 products on the starter plan reserves 3 store generations; with too little left the screen offers deselection.
- Undo removes only `ManagedResource` items of this blueprint.

## Assumptions made during build
_(to be filled in by Hermes)_

1. **T-111 `is_complete()` purposes** (12 §2.1 lists the four purposes but not their required fields):
   - `legal` → legal_name, street, postal_code, city, country_code, email (the facts the withdrawal model form shows).
   - `contact` → legal_name, email (the GPSR contact page needs who to contact; a street is shown only when present — never invented).
   - `impressum` → `legal` + company_reg_no (07: required for the German Impressum).
   - `returns` → legal_name, street, postal_code, city, country_code; when `return_address_same` is False additionally a non-empty `return_address` JSON.
2. **VAT ID check**: "format check per country prefix only" implemented as `vat_id` starting with `country_code` (case-insensitive) in `clean()`; no per-country structure validation (no regex zoo) — the lawyer pass (T-090) may tighten this.
3. **Template placeholder policy**: placeholders whose facts are missing stay in the rendered page (visible draft state) rather than being blanked; `fill_legal_details` fills an address placeholder only when street AND postal_code AND city are all present.
