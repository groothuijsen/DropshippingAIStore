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

### T-112 (2026-10-02)

1. **Onboarding flow wiring**: the onboarding views existed but had no URL registration and no templates — T-112 added `/app/onboarding/` routes and minimal functional templates for all six steps so the brand step (F15-1) is reachable. Step screens are intentionally plain; polish can come later.
2. **`_get_shop` fix**: onboarding read `request.shop_id`, which `SessionTokenMiddleware` never sets (it sets `shop_domain`) — every onboarding request returned 401. Now resolves by domain like every other app view.
3. **Names panel polling**: HTMX (`hx-trigger="every 3s"` against `/app/start/panel/`) using the vendored `static/vendor/htmx.esm.js` that `auth.js` already loads; no meta-refresh fallback (the wizard only renders inside the admin iframe where auth.js runs).
4. **Empty `audience` is schema-valid** (docs/12 §3 `Field(max_length=200)` has no min) — accepted as-is.
5. **Second names call asks for the missing count** but the schema returns 8 per call; the task merges, dedupes and keeps the first 8 passing names.
6. **Brand-blocklist matching**: brands ≤3 chars match exactly, longer as substrings; generic-claim terms (≥3 chars) and geographic origins match as substrings (`EcoGlow`, `SwissSleep` rejected).
7. **RDAP = rdap.org per spec**; .com only; live-verified (404 free / 200 taken). Q21 answered in open-questions.md.
8. **AI model**: `model_key="copy"` (→ `LLM_MODEL_COPY`, currently `claude-sonnet-5-5`) per the niche_names.md prompt header. That model rejects forced `tool_choice` and `temperature` (400) — `AnthropicClient._make_request` drops the offending param and retries once; schema validation unchanged. Client also falls back to `settings.ANTHROPIC_API_KEY` because the systemd units do not load `.env` into the process environment.

### T-113 (2026-10-02)

1. **`BrandKit.tagline`** added (migration themes/0002): F15-5 requires the form to show the tagline and saving to persist it; BrandKit is the brand-config home. Design tokens stay exactly as F05-5 defines them (tagline not added to tokens).
2. **Proposal corrections** (prompt: "The code re-checks contrast and font keys"): invalid font keys fall back to `""` (inherit theme font); a failing text-on-background contrast is corrected with `validate_palette`'s darker-text suggestion — a proposal is never stored or saved with a failing contrast.
3. **Task idempotency**: `generate_brand_proposal` no-ops when `brand_proposal` is already set or the status isn't `brand`; the brand-step GET may double-enqueue safely.
4. **After brand save the wizard shows an ideas placeholder** (status `ideas`); the real product-ideas screen is T-114. Onboarding itself is not advanced — sources/theme/withdrawal still run after the wizard per F15-1.
5. **`sync_brand_tokens`** was previously defined but never called by any save path — F15-5's "writes the BrandKit and design tokens exactly as F05-5" required wiring it (Celery task, decrypts the stored token).
6. **`call_ai` returns the validated model only** (not `(model, usage)`); the names task already relied on this, the brand task initially unpacked a tuple — live E2E caught it.
7. **Presets carry a `description`** now (data addition to `STYLE_PRESETS`) because the niche_brand prompt variable `presets_json` asks for "the 6 presets with their description".

### T-114 (2026-10-02)

1. **Import-app deep links** (06 §4 app list has detection rules but no public URLs): CJ and Printify get search-style links (URL-encoded phrase appended); DSers/Zendrop/AutoDS/Printful link to their app surface; `manual`/`other` get no link (the continue button still works). URLs are merchant-facing links only — the app never requests them server-side.
2. **`started_products_at` first-click-wins**: re-clicking "continue" keeps the original window so products imported before a re-click stay listed; the timestamp updates only when it was null.
3. **`selected_product_gids` + `imported_products` added in the same migration wave** (§2.2 fields T-115 needs) — one migration instead of several.
4. **Ideas/import screens are polled via HTMX**; the fallback products query runs server-side on every 10s poll while the page is open (F15-7), first 50 products, deduped by GID against webhook records.
5. **Model/temperature**: `model_key="research"` (`LLM_MODEL_RESEARCH`) and temperature 0.6 per the product_ideas.md prompt header.
6. **Webhook HMAC (critical, found 2026-10-02)**: the receiver validated `sha256(secret + body)` instead of HMAC-SHA256 keyed with the app secret over the raw body. Every test/E2E signer used the same wrong formula, so self-signed tests passed while every live Shopify delivery returned 401 and no receipt was ever stored (the T-131 PriceHistory gap and the missing F15-7 webhook signal were this one bug). Fixed in `apps/webhooks/hmac.py`; regression test asserts the keyed HMAC validates and the old formula does not. Lesson: never sign test webhooks with code copied from the validator — verify against a real delivery.
7. **Webhook product IDs are plain numeric**, the Admin API returns GIDs — `_record_imported_product` prefixes digit IDs (`str()` guard: payloads may carry `id` as an int) and the panel merge normalizes both shapes.
8. **Plan maximum** comes from `PLAN_LIMITS[*]["products_per_build"]` (12 §7: starter 5, pro 20, agency 20); the selection screen disables Next at 0 selected and the server rejects 0 or over-max (`BLUEPRINT_NO_PRODUCTS` / plan-max message).

### T-115 (2026-10-02)

1. **`store_structure` runs as a plain Celery task** (like names/brand), not a `GenerationJob` sequence — the build job (T-117) owns job bookkeeping. Failure surfaces via `StoreBlueprint.structure_error` (plain English merchant message; the wizard renders it as-is).
2. **Repair-once semantics** (F15-8): collections referencing GIDs outside `selected_product_gids` trigger exactly one retry with a repair note listing the valid GIDs; a second violation fails with a merchant message and keeps status `structure` (retry button re-enqueues).
3. **Edits are saved per operation** into `store_structure` (rename/move/delete/add) — there is no separate draft field; confirm re-validates the edited tree (coverage, shipping+returns, menu refs, menu 3–8) and advances to `building`. The build job itself is T-117.
4. **Page titles are NOT part of the AI structure** (12 §3 pages are literals only) — titles/descriptions come from the page templates at build time (T-116/T-117).
5. **Product data for the prompt**: `products_by_ids.graphql` (nodes(ids:), priceRange.minVariantPrice) — fixture `tests/fixtures/shopify/products_by_ids.json` captured from the dev store.
6. **Legacy webhook int IDs**: `imported_products` rows written before the T-114 str() guard hold numeric ids as ints; `_norm_gid` stringifies (live 500 found this; regression test added).

### T-118 (2026-10-02)

1. **Q20 answered**: a best-effort theme-editor deep link (`/admin/themes/current/editor?template=index&add_header_menu=mosaiq-main`, same family as the documented 03 §7 links) plus a "Done" checkbox — without `read_themes` the app cannot resolve the active theme or verify the parameter, so the checkbox is the source of truth (same stance as the 09 onboarding theme step).
2. **The home page publishes as a metaobject only** — `home` is not in `PAGE_TYPES_NEEDING_SHOPIFY_PAGE` (it renders via the theme homepage + `SHOP:home_page` metafield), so it has no `/pages/` entry and shows `gid: null` in the publish result; the menu covers it via FRONTPAGE.
3. **GPSR preconditions apply to product pages only** in `check_can_go_live` (the empty-`GpsrInfo` check blocked every standard page live; GPSR duties attach to products — same scoping as the T-117 publish-step gate).
4. **Undo is unit-tested but deliberately not exercised live** on the dev store (it would delete the built store); the same GraphQL mutations are verified read-side by the publish E2E.
5. **A Shopify page publish failure blocks the page** (F07-5 requires metaobjects ACTIVE + page published + status live together); `publish_store` lists such pages as blocked instead of marking them live.

### T-117 (2026-10-02)

1. **ManagedResource gained a `title` field** (not in the 12 §2.3 table): menu items need their display title; handle alone cannot recover it after a rename.
2. **Standard-page child jobs exist only for page types with generated content** — a type requested by the structure but missing from `standard_pages` is skipped and listed in the children step output, instead of creating a job that would fail at layout.
3. **The home page is built from real data, not AI copy**: hero = brand name + BrandKit tagline (fallback: brief description). The T-060x copy step upgrades it later; no invented content.
4. **Parent steps reuse the existing StepName enum** with F15 meanings: import=limits, research=collections, copy=children, publish=menu — avoids enum churn; meanings documented in store_build.py.
5. **Reservation conversion is a single point**: the parent consumes/releases the composite reservation (store_generations + ai_images) on terminal success/failure; children carry `usage_reserved` and never reserve/consume individually. In-process reservation bookkeeping falls back to recomputation from the blueprint after a worker restart.
6. **A failed child keeps the parent RUNNING** (per 12 §5: no rollback; per-item Retry on the status screen); the menu step runs only when ALL children succeed, via advance_store_build after each child and directly on a resume where children already finished.
7. **Auto-angle selection** (live E2E): F15 store builds have no angle screen (that was the F04 manual flow); PDP children pick the research angle deterministically — best keyword match against description/audience/brand, ties → first angle (`_auto_angle`).
8. **needs_input blocks the menu step** — the first live build published the menu while the PDP child still hung in needs_input; `children_state` now counts every non-terminal status as incomplete.
9. **Pages are created unpublished** (isPublished=false via the existing publish step); publishing collections/pages and menu placement are T-118 (go-live) concerns — nothing touches main-menu or themes (F15-10).

### T-116 (2026-10-02)

1. **One AI call generates ALL standard page types** of the structure (schema `StandardPages`), not one job per type — per-type child jobs are a T-117 build concern; content generation is batched for cost.
2. **`about` is not in the 12 §3 section-rules table** (only faq/shipping/returns): assembled as rich_text intro (+ faq if the AI returned items); recorded here as the safest interpretation.
3. **The returns page links to `/pages/withdrawal`** — the withdrawal page the legal app creates at go-live (07 §7); no route exists in this repo yet.
4. **Fact blocks are localized at generation time** (nl/en/de translation map in `standard_pages.py`); sections are stored for the shop's first content locale only.
5. **Digit guard** (F15-16): any digit in AI-written fields triggers ONE repair round; a second leak keeps the text with a `verify_numbers` warning instead of failing the flow (merchant visibility over hard failure).
6. **Collection renames cascade to menu refs** (fix from the T-116 E2E): menu items whose `ref` equals the old collection title follow the rename, so confirm's ref validation stays satisfiable. Pre-fix blueprints with stale refs need a one-time data repair (dev store repaired during E2E).

### T-111 (2026-10-01)

1. **T-111 `is_complete()` purposes** (12 §2.1 lists the four purposes but not their required fields):
   - `legal` → legal_name, street, postal_code, city, country_code, email (the facts the withdrawal model form shows).
   - `contact` → legal_name, email (the GPSR contact page needs who to contact; a street is shown only when present — never invented).
   - `impressum` → `legal` + company_reg_no (07: required for the German Impressum).
   - `returns` → legal_name, street, postal_code, city, country_code; when `return_address_same` is False additionally a non-empty `return_address` JSON.
2. **VAT ID check**: "format check per country prefix only" implemented as `vat_id` starting with `country_code` (case-insensitive) in `clean()`; no per-country structure validation (no regex zoo) — the lawyer pass (T-090) may tighten this.
3. **Template placeholder policy**: placeholders whose facts are missing stay in the rendered page (visible draft state) rather than being blanked; `fill_legal_details` fills an address placeholder only when street AND postal_code AND city are all present.
