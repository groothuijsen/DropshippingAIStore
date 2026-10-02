# Sprint plan and tickets

Numbering per domain (not per sprint). Sprints of 2 weeks; 6 sprints = MVP (weeks 3–14 of the plan). Only pick up a ticket once all dependencies are `done`.

## Tickets

| Ticket | Title | Spec / docs | Depends on | Status |
| --- | --- | --- | --- | --- |
| **Foundation** | | | | |
| T-001 | Repo scaffold: Django 5.2, uv, apps from 01, Docker Compose dev, Makefile, ruff/mypy/pytest, CI workflow | 00, 01 | — | ✅ done |
| T-002 | Session token validation (middleware, bounce page) + token exchange with `expiring=1` + refresh with Redis lock + `keep_tokens_fresh` + `Shop` model + Fernet | F00, 03 §2–2.3a | T-001 | ✅ done |
| T-003 | Embedded layout: App Bridge, Polaris web components, HTMX + `auth.js`, CSP middleware, i18n nl/en/de | F00, 03 §2.4–2.5, 09 | T-002 | ✅ done |
| T-004 | Webhook endpoints, HMAC, dedupe, `WebhookReceipt`, dispatch task | F00, 03 §3 | T-002 | ✅ done |
| T-005 | GraphQL client (throttling, errors, `get_access_token()`), `scripts/gql.py`, `.graphql` loader | 01, 03 §4–5 | T-002 | ✅ done |
| T-006 | Installation tasks: shop data, metaobject/metafield definitions, log/check resolved namespace | F00, 03 §5–6 | T-005 |  ✅ done |
| T-007 | Price snapshot on installation + `products/update` → `PriceHistory` | F11-A, 03 §6 | T-006 |  ✅ done |
| **Pipeline** | | | | |
| T-010 | `GenerationJob`/`JobStep`/`AiCall`, orchestration with checkpoints, error codes, cost budget | 05 §1–2, §5 | T-005 |  ✅ done |
| T-011 | AI clients: Anthropic tool use + schema validation + repair attempt + cost logging | 05 §2–3, 00 | T-010 |  ✅ done |
| **Sources and import** | | | | |
| T-020 | Source detection via fulfillment location (`variant_locations`, `SOURCE_RULES`, storage `Shop.import_apps`) + verification of rules with `False` (06 §4.4). The onboarding screen itself belongs to T-031 | F01, 06 §4 | T-006 |  ✅ done |
| T-021 | Ownership guard `assert_writable` + tests on all product mutations | F01-3, 06 §3 | T-020 |  ✅ done |
| T-022 | Step `import` (existing, manual, URL facts) + product picker UI | F01, 05 §4.1 | T-011, T-021 |  ✅ done |
| **Brand and extension** | | | | |
| T-030 | BrandKit, presets, verify font list, tokens to app metafield | F05 | T-006 |  ✅ done |
| T-031 | Onboarding flow: steps `language`, `brand`, `sources`, `theme` (deep links + guided Mosaiq templates); step `withdrawal` as a temporary stub until T-085 | F05-1..2, 09 | T-030, T-020, T-032 |  ✅ done |
| T-032 | Theme App Extension scaffold, `mq-tokens` with bundled fonts, read shop metafields via `$app:mosaiq` (03 §5.3), deep links (03 §7), locales check script, uninstall behavior of blocks | F06, 04 §1, 03 §5.3, §7 | T-030 |  ✅ done |
| T-033 | Block `mq-page-sections` (all section types) + admin preview templates | F06-7, 09 | T-032 |  ✅ done |
| **Research, copy, compliance check** | | | | |
| T-012 | Step `research` + angle selection UI | F02 | T-022 |  ✅ done |
| T-013 | Step `copy` + guardrails + language detection + create `Page` | F03-1..5, 7 | T-012, T-087 |  ✅ done |
| T-080 | Claims: blocklist per language + AI check + `ClaimFinding` + score | F11-D, F11-H, 07 §4, §9 | T-013 |  ✅ done |
| **Images** | | | | |
| T-040 | Vertex image provider (verify model ID, Q2) + OpenAI fallback + shot plan | F04-1..2, `prompts/images.md` | T-011 |  ✅ done |
| T-041 | Fidelity check | F04-3 | T-040 |  ✅ done |
| T-042 | C2PA signing + staged upload + `fileCreate` + limit + AI label | F04-4..8, F11-12 | T-041, T-061 |  ✅ done |
| T-043 | Test with `c2patool`/`exiftool`: C2PA on original in Files and on `?width=800&format=webp` (Q3); update 07 §6 | F04-9 | T-042 |  ✅ done |
| **Pages** | | | | |
| T-050 | Steps `layout` + `publish` (draft) + GPSR check before publish + store job with child jobs | F07-1, 05 §1, §4.6 | T-013, T-033, T-042, T-080, T-082 |  ✅ done |
| T-051 | Page editor, rewriting, overrides, recheck/resume, set live, archive | F07-2..8 | T-050, T-080, T-061, T-083 |  ✅ done |
| T-052 | Save/reuse templates | F08 | T-051 |  ✅ done |
| T-053 | Translate into additional store languages (own metaobject entry per language, 03 §5.1) | F03-6 | T-051 |  ✅ done |
| **Billing** | | | | |
| T-060 | Plans, `appSubscriptionCreate`, verify return URL, status webhook (basic), access gate | F12-1..3, 08 §2–3 | T-004, T-005 |  ✅ done |
| T-061 | Limits + `UsageCounter` with `select_for_update` | F12-6, 08 §1 | T-060, T-010 |  ✅ done |
| T-062 | TrialLedger, trial reminders, upgrade/downgrade, cancellation, reconcile | F12-4..5, 7..9 | T-060 |  ✅ done |
| **Offers and cart** | | | | |
| T-070 | Discount Function (`cart.lines.discounts.generate.run`; volume, BOGO, gift) + config metafield test first + Function tests | F09-4, 04 §2 | T-032 |  ✅ done |
| T-071 | `Offer` model, editor, activate/deactivate (discount + metaobject + metafield) | F09-1..2, 5, 7 | T-070, T-083 |  ✅ done |
| T-072 | Block `mq-bundle-picker` + `mq-price` (price, savings, unit price, timer, stock and cut-off rules) | F09-3, 6, 8, F11-7, 04 §1 | T-071, T-083, T-081, T-087 |  ✅ done |
| T-073 | Embed `mq-cart-drawer` (upsells, rewards bar) | F10 | T-071 |  ✅ done |
| **Remaining compliance and cleanup** | | | | |
| T-081 | Omnibus: `prior_price`, `reduction`, attestation, daily metafield task | F11-A, 07 §1 | T-007 |  ✅ done |
| T-082 | GPSR model, form, copying, block `mq-gpsr` | F11-E, 07 §5 | T-032 |  ✅ done |
| T-083 | Unit price model, form, calculation | F11-B, 07 §2 | T-006 |  ✅ done |
| T-084 | Uninstall, `shop/redact`, export; verify what Shopify leaves behind | F13 | T-004, T-060 |  ✅ done |
| T-085 | Legal pages (draft templates) + `mq-withdrawal-link` + onboarding step withdrawal (checklist 07 §8.4) | F11-G, 07 §7–8 | T-032 |  ✅ done |
| T-088 | Withdrawal form via app proxy (two steps, `WithdrawalRequest`, confirmation email, merchant overview, GDPR webhooks) | F11-G, 07 §8.1–8.3, 02, 03 §1 and §3 | T-085, T-004 |  ✅ done |
| T-086 | Support page and form | F14 | T-003 |  ✅ done |
| T-087 | Store settings (`/app/settings/store/`): warranty policy, shipping cut-off, AI label default, stock threshold → `Shop` + app-data metafield `settings` | 09, 02 `Shop`, 03 §5.2 | T-003, T-006 |  ✅ done |
| **Launch** | | | | |
| T-090 | Lawyer review: templates, labels 07 §8.2 (incl. Belgium), terms, AI Act role (Q7); remove draft banner | 07, open-questions | T-085, T-088 | |
| T-091 | Evalset (30 products) + `make eval` + first report | 10 §4 | T-013, T-042 |  ✅ done |
| T-092 | Manual release checklist + Lighthouse | 10 §5 | all MVP |  ✅ done |
| T-093 | App Store listing NL/EN/DE, screenshots of demo stores (wellness/sleep, car accessories, POD merch) | plan document GTM | T-092 | |

## Sprint allocation

| Sprint | Weeks (plan) | Tickets |
| --- | --- | --- |
| S1 | 3–4 | ~~T-001~~, ~~T-002~~, T-003, T-004, T-005, T-006, T-007 |
| S2 | 5–6 | T-010, T-011, T-020, T-021, T-060, T-030 |
| S3 | 7–8 | T-022, T-032, T-031, T-033, T-061, T-083, T-082, T-087 |
| S4 | 9–10 | T-012, T-013, T-080, T-040, T-041, T-081, T-070 |
| S5 | 11–12 | T-042, T-043, T-050, T-051, T-071, T-072, T-062 |
| S6 | 13–14 | T-052, T-053, T-073, T-084, T-085, T-088, T-086, T-091, T-092 |
| Beta | 15–18 | bug fixes, T-090, T-093 |

If a sprint overruns: first move T-052, T-053 and T-073 to v1.1 (not the compliance tickets).

## v1.1 tickets — store builder additions (F15–F18, see 12)

Pick these up only after the MVP release checklist (T-092) passes. Recommended order: F18 and F17 first (small, compliance value), then F15, then F16.

| Ticket | Title | Spec / docs | Depends on | Deliverable |
| --- | --- | --- | --- | --- |
| **Foundation v1.1** | | | | |
| T-110 | Scopes `write_online_store_navigation` + `write_publications`, webhook `products/create`, scope check + re-grant screen; fixtures for `collection_create`, `publications`, `publishable_publish`, `menu_create`, `menu_update`, `menu_delete`, `collection_delete`, `page_delete`, `product_variants_bulk_update`, `inventory_item_cost`; answer Q18/Q19 | 12 §4, F15-2 | T-092 | **DONE** 2026-10-01. All fixtures live-captured after scope re-grant (grant verified: 15 scopes incl. the 3 new ones; token refreshed). Q18 + Q19 answered. Webhook `products/create` registered on dev store (subscription verified live). Receiver fixes (shop_domain header, body_json) + `handle_product_create` + `/auth/callback` route deployed — pending gunicorn/worker restart. |
| T-111 | `BusinessDetails` model + settings screen; legal templates (07 §7) and contact page filled from it; `is_complete()` | 12 §2.1, F15-9 | T-085 | **DONE** 2026-10-01. Model + `is_complete()` (legal/contact/impressum/returns), VAT prefix check in `clean()`, `fill_legal_details()` applied in `get_legal_pages()`, `/app/settings/business/` form + AuditLog. Migration 0004 applied on VPS; deployed + restarted; route verified live (App Bridge loader, auth required). 907/907 tests. |
| **Delivery times (F18)** | | | | |
| T-140 | `DeliveryProfile` + `DeliveryOverride` models, settings and product screens, `estimate()` | F18-1..3, 12 §2.4 | T-111 | **DONE** 2026-10-01. Models + estimate() + validation deployed; migration 0003 applied; 922/922 tests. Settings/product screens (F18-1..2 UI) + metafield sync (F18-4) in T-141/T-142. |
| T-141 | Delivery metafield sync task + `mq-price` rendering + cut-off suppression + 30-day block | F18-4..7, 12 §8 | T-140, T-072 | **DONE** 2026-10-01. sync_delivery_metafields (batched 25, default_market = first entered market), mq-price delivery line (per-visitor-market + fallback, nl/en/de), DELIVERY_OVER_30_DAYS in check_can_go_live, delivery metafield definition registered. Cut-off notice itself not yet rendered by any theme block — suppression condition tested at estimate level. 935/935 tests. |
| T-142 | Claim rule `SHIPPING_CLAIM` + copy-step input/guardrail + 5 evalset cases | F18-8..9, 12 §5, §8 | T-140 | **DONE** 2026-10-01. Context-aware SHIPPING_CLAIM (block max_days>3, warn no-estimate, EU-ship check); delivery_guardrail() in copy_step; 5 long-delivery eval cases (max 18-25). 948/948 tests. Sprint S7 complete. |
| T-143 | Delivery settings UI screens: profiles per source app + product override form | F18-1..2, 12 §6 | T-140 | **DONE** 2026-10-02. /app/settings/delivery/ (rows per source app, JSON transit/cost, full_clean validation, AuditLog, sync trigger) + /app/products/<gid>/delivery/ (override with profile fallback, empty POST = delete). Templates nl/en/de. 958/958 tests. F18 criteria 1-2 closed — F18 fully done except F18-6 notice block (theme block pending) + F18-10 shipping page (T-116). |
| **Price advisor (F17)** | | | | |
| T-130 | `PricingSettings`, VAT table, `advise()` with the exact test cases, advisor screen | F17-1..3, 6..7 | T-110 | **DONE** 2026-10-02. vat_rates.py (7 EU rates + source/date, GB not covered); advise() exact F17 formula (all 5 cases pass); PricingSettings editable at /app/settings/store/; advisor screen /app/products/<gid>/pricing/ with breakdown + Omnibus-ready display. 976/976 tests. Apply (F17-4/5) = T-131. |
| T-131 | Apply price for writable products + guard tests for sync-app products + audit log | F17-4..5 | T-130, T-021 | **DONE** 2026-10-02. PriceAdvice model (migration 0005); apply endpoint with assert_writable guard + AuditLog; sync-app refused before any HTTP call; current-price display + Omnibus warning (F17-3 remainder + F17-6) completed here; live E2E: price 24.95 written to dev store, PriceHistory via products/update webhook (subscription was missing live — registered, fixture saved). 987/987 tests. |
| **Start from zero (F15)** | | | | |
| T-112 | `StoreBlueprint` model + route choice in onboarding `brand` + brief screen + names step (prompt `niche_names`, blocklists, RDAP check, TMview link, regenerate) | F15-1, 3, 4; 12 §2.2 | T-110 | **DONE** 2026-10-02. StoreBlueprint (generator/0002) + Shop.onboarding_route (core/0005); brand-step route choice (zero → /app/start/, existing waits for BrandKit); created missing onboarding templates + URL wiring; fixed _get_shop (request.shop_id never set → 401); /app/start/ brief (NicheBrief validation) + HTMX names panel; generate_name_suggestions task (niche_names.md → 8 names → blocklist + 1 repeat → RDAP .com); brand_blocklist.py (EcoGlow/Nike/SwissSleep rejected); 1020/1020 tests. LIVE E2E: full flow + 8 REAL AI names + RDAP correct + pick saved. Q21 answered. |
| T-113 | Brand step (prompt `niche_brand`) → existing BrandKit form | F15-5 | T-112, T-030 | **DONE** 2026-10-02. BrandProposal schema (12 §3); StoreBlueprint.brand_proposal (generator/0003) + BrandKit.tagline (themes/0002); generate_brand_proposal task (model_key copy, tool submit_brand, temperature 0.4) with F05 corrections (invalid fonts → inherit, low-contrast text corrected via validate_palette suggestion); pick enqueues task; brand step HTMX-poll → pre-filled BrandKit form; save → BrandKit + tagline + blueprint status ideas + sync_brand_tokens.delay (design tokens wiring — sync was defined but never called); wizard shows ideas placeholder. LIVE E2E: real AI proposal (warm/soft/lora + Dutch tagline) → prefill verified → save → tokens_synced_at set on dev store. 1038/1038 tests. |
| T-114 | Product ideas (prompt `product_ideas`) + import-waiting screen (webhook + poll) + selection | F15-6, 7 | T-113 | **DONE** 2026-10-02. F15-6: ProductIdea/ProductIdeas schemas; started_products_at + selected_product_gids + imported_products (gen/0004-0005); generate_product_ideas task (research, temp 0.6); import_apps.py deep links; wizard ideas screen + start_import (first-click-wins). F15-7: products_per_build limits (5/20/20); products/create webhook records products on the blueprint (GID-normalized); import-waiting panel merges webhook + 10s fallback query, vendor source detection, selection 1–20 with plan max, BLUEPRINT_NO_PRODUCTS at 0, status → structure. **CRITICAL FIX: webhook HMAC was sha256(secret+body) instead of keyed HMAC-SHA256 — every live delivery returned 401 since T-110; self-signed tests masked it.** LIVE E2E: 10 real AI ideas → import window → product listed via fallback → selected → structure; after HMAC fix live receipts + imported_products verified with full GIDs. 1065/1065 tests. |
| T-115 | Structure proposal (prompt `store_structure`) + editable tree | F15-8 | T-114 | **DONE** 2026-10-02. StoreStructure/CollectionPlan/MenuItemPlan schemas (12 §3); StoreBlueprint.store_structure + structure_error (gen/0006); generate_store_structure task (copy, temp 0.3, products_by_ids query, ONE repair round for GIDs outside the selection → merchant message); select_products enqueues the proposal; wizard editable tree (rename/reorder/remove/add collection+page, floors 1/3/2); confirm validates coverage + shipping/returns + menu refs → status building. LIVE E2E: real AI proposal (1 collection for 1 product, menu 4, shipping+returns) → confirm → building; rename live-verified after _norm_gid int-guard fix (legacy webhook rows). 1086/1086 tests. |
| T-116 | Page types `faq`, `shipping`, `returns`: schemas, section rules, fact blocks from models, `mq-page-sections` rendering | 12 §3, F15-16, F18-10 | T-111, T-140, T-050 | **DONE** 2026-10-02. PageType += faq/shipping/returns + standard_pages field (gen/0007); StandardPages schemas + standard_pages.md prompt (AI writes intro+FAQ ONLY, hard no-numbers rule); standard_pages.py fact blocks — shipping renders per-market days+costs from DeliveryProfile (no profile → 'Delivery times missing' + missing_facts per F18-10), returns renders14-day withdrawal block (/pages/withdrawal) + address from BusinessDetails (D-15.4), nl/en/de; digit guard (1 repair round → verify_numbers warning, F15-16); structure_confirm enqueues; building panel shows pages + warnings. LIVE E2E: re-confirm → real AI shipping+returns content generated, no delivery profile → missing_facts warning shown. 1102/1102 tests. Related fix: collection rename now cascades to menu refs (confirm validation caught the stale-ref state live). |
| T-117 | `store_build` job: limit reservation, collections, page/PDP child jobs, menu, `ManagedResource`, status screen, retry, idempotency | F15-10, 11, 15; 12 §5, §7 | T-115, T-116 | **DONE** 2026-10-02. ManagedResource model (gen/0008, 12 §2.3 + title field for menu labels); StoreBlueprint.build_job + store_limit_reserved_at; store_build.py — limits in ONE transaction (store_generations 1+(n−1) + ai_images n), collections UNPUBLISHED via collectionCreate (real T-110 sources shape) + ManagedResource rows, child jobs (standard pages → local Page + layout/publish; home from BrandKit; PDP children with the FULL pipeline + usage_reserved), menu mosaiq-main LAST via menuCreate/menuUpdate; run_store_build (4-step parent, resume, last_error, PLAN_LIMIT_REACHED/BLUEPRINT_NO_PRODUCTS); advance_store_build (failed child keeps parent running); build panel with steps Done/Running/Error + per-child Retry. 1129/1129 tests. LIVE E2E (dev store): full build GREEN — collection `live-geverifieerd` (unpublished) + Shopify pages for home/shipping/returns (metaobjects via the REAL 2026-07 shape) + menu `mosaiq-main` created; parent succeeded. The E2E exposed and fixed a chain of never-run-against-real-API issues: render_prompt tuple as system= + dead model keys ("claude"/"sonnet") in research/copy/import steps; get_pending_steps auto-creating the product pipeline for standard pages (now SKIPPED); GPSR gating non-product pages; error_code varchar(60) overflow masking failures; metaobjectUpsert pre-2026-07 query shape (deviation fixture recorded); wrong metaobject type string (real: app--430212644865--page_content); layout emitting per-section field keys instead of the definition's sections-JSON shape; needs_input children slipping past the menu gate; auto-angle selection for PDP children (no angle screen in F15). Commits ece5249..f86f00c. PDP child: research+auto-angle live; publish will surface GPSR_INCOMPLETE until the merchant fills GPSR (07 §4, by design). |
| T-118 | Menu placement step + "Publish store" (go-live + collection publish) + Undo | F15-12..14 | T-117 | **DONE** 2026-10-02. StoreBlueprint.menu_placed + publish_result (gen/0009); store_go_live.py — publish_collections (Online Store publication + publishablePublish), publish_store (F07 go-live per eligible page, BUSINESS_DETAILS_MISSING for returns, blocked reasons in publish_result + AuditLog), undo_store_build (live pages block; else collectionDelete/menuDelete/pageDelete + local archive + removed_at + AuditLog per deletion; products/BrandKit untouched); menu placement explainer + theme-editor deep link + Done checkbox; Publish/Undo panel sections. Q20 answered (best-effort editor link; Done checkbox is the source of truth without read_themes). LIVE E2E: collection → Online Store verified read-side; shipping page isPublished=True; returns correctly blocked with BUSINESS_DETAILS_MISSING. 1145/1145 tests. Live-found+fixed: pageUpdate needs top-level id (2026-07, introspection fixture page_update_shape.json); go_live aborted silently on publish failure → now blocks honestly; GPSR precondition scoped to product pages. Undo unit-tested; live undo deliberately NOT run (would delete the dev store). |
| **App UI polish (user request 2026-10-02)** | | | | |
| T-160 | UI styling: WhiteNoise static serving + Carbon Emerald stylesheet + dead-nav cleanup | — | user request | **DONE** 2026-10-02. WhiteNoise middleware + CompressedStaticFilesStorage (prod /static/* was 404 — no nginx on CT 412); collectstatic live. styles.css: full Carbon Emerald theme (direction C from the 3-way mockup the user picked) — semantic tokens, all 50 mq-* classes, forms/tables/steps/messages/cards, 44px targets, focus-visible rings, dark scrollbar. dashboard.html rewritten: emoji icons + dead links (generate/pages/offers — screens not built) removed, cards link only built screens (start, delivery, settings). Live E2E: /static/app/styles.css 200; app root + store settings + delivery all render rgb(14,15,15) with emerald accents, zero white areas, zero emoji. Commits 749142a + 3a9f2f0. Mockup artefact: ~/Documents/Hermes/mosaiq-ui-directions-2026-10-02.html |
| T-161 | GPSR form + GPSR loaded from the product metafield + pipeline contract fixes | F11-E, 07 §5, 05 §4.6 | T-082, T-117 | **DONE** 2026-10-02. gpsr_form view (`/app/products/<gid>/gpsr/`, gen route + template): writes `$app:mosaiq.gpsr` (json) via metafieldsSet + AuditLog `gpsr_saved`; incomplete saves allowed with missing-fields warning (publish stays blocked); EU-RP help per 07 §5; browser gid-collapse repair (`gid:/shopify` → `gid://shopify`); Shopify errors surface in the form, never 500. gpsr_loader.load_gpsr_info: publish_step + go_live + check_can_go_live read the metafield (empty → gate blocks; API failure degrades to empty). Build panel links blocked PDPs to the form (URL-encoded gid). New query product_metafield_get (live-verified, fixture). **Live E2E (dev shop)**: form fill → metafield verified via API read → PDP publish gate sees complete=True → FULL PDP pipeline ran green (compliance 100 → layout → publish, metaobject 284940402982, MR registered). The E2E exposed and fixed a chain of never-run-against-real-API bugs: (1) execute_job marked steps SUCCEEDED with None output — contract steps now raise (CopyInputMissing/PageNotFound/STEP_NO_OUTPUT); (2) run_copy treated the validated Pydantic payload as dicts (`'Hero' has no attribute 'get'`) → model_dump first; (3) images/compliance_check read the wrong checkpoint shape; (4) AI repair messages synthesized tool_use without id (Anthropic 400) → replay original content; (5) OpenAI image provider posted form-encoded to /images/edits without refs → JSON generations endpoint + integer n + supported sizes + settings-driven model (gpt-image-1.5 on VPS); (6) Page.compliance_findings field never existed (migration 0010); (7) google-genai dependency undeclared. 1163/1163 tests. Commits 83282f1..HEAD. |
| T-162 | Phase close-out: F18-6 cut-off block + home ManagedResource gap | F18-6, 12 §2.3 | T-160 | **DONE** 2026-10-02. mq-price.liquid renders the 07 §3 cut-off notice (nl/en/de `price.cutoff_notice`) only on configured shipping days before the cut-off time; suppressed when product max_days > ship_cutoff.delivery_days (F18-6 criterion 6). register_page_resources now also registers metaobject-only pages (home) as ManagedResources; undo_store_build deletes metaobject MRs via metaobjectDelete. Live: home metaobject 284621013286 registered on the dev store (was missing → Undo couldn't remove it). tests/test_t162.py. Theme-extensie deploy (cut-off block) nog nodig via `shopify app deploy` (CLI niet op de VPS). |
| **Plain-language edits (F16)** | | | | |
| T-120 | `PageEdit` model, prompt `edit_page`, operation validation and apply engine, `page_edits` limit | F16-2, 4, 5, 8; 12 §3 | T-051 | criteria F16-2, 4, 5, 8 |
| T-121 | Editor UI: instruction field, per-section button, diff view, apply/reject, other languages | F16-1, 3, 6, 7, 9 | T-120 | criteria F16-1, 3, 6, 7, 9 |

| Sprint | Tickets |
| --- | --- |
| S7 | T-110, T-111, T-140, T-141, T-142 |
| S8 | T-130, T-131, T-112, T-113 |
| S9 | T-114, T-115, T-116, T-117 |
| S10 | T-118, T-120, T-121 |

## v1.2 tickets — marketing site and sales copy (F19, see 13)

Start after the v1.1 tickets (S10) are done, so the site describes what actually ships. T-093 (App Store listing) now uses `docs/marketing/app-store-listing.md` and depends on T-156 (privacy policy URL).

| Ticket | Title | Spec / docs | Depends on | Deliverable |
| --- | --- | --- | --- | --- |
| T-150 | `apps/marketing`: host guard (`shopify.mosaiq.marketing`), language-prefixed routes, content loader + section schemas, `check_marketing_content` in CI; remove `apps/core/salespage.py` | F19-1, 2; 13 §2–4 | T-121 | criteria F19-1, 2 |
| T-151 | Site design: self-hosted fonts (+ licences), tokens, templates per section type, OG image generation, no third-party requests test | F19-5; 13 §5 | T-150 | criterion F19-5; answer Q22 |
| T-152 | Transfer EN and NL copy into content files, link claims, update `claims.md` statuses | F19-3; `docs/marketing/site-copy.*.md`, `claims.md` | T-151 | all EN/NL pages render; check passes |
| T-153 | Pricing table from `plans.py`; comparison section with `last_checked`, sources, 90-day reminder, 120-day auto-hide | F19-4, 11 | T-152 | criteria F19-4, 11 |
| T-154 | SEO: sitemap, robots, canonical, hreflang, JSON-LD; cookieless self-hosted analytics; Lighthouse ≥ 95 in CI | F19-6, 8, 9; 13 §5 | T-152 | criteria F19-6, 8, 9 |
| T-155 | `Lead` model, early-access form, double opt-in, honeypot + rate limit, emails 1–2, unconfirmed-lead cleanup, `@install` switch via `MARKETING_APP_LISTED` | F19-7; 13 §6; `emails.md` §1–2 | T-150 | criterion F19-7; answer Q24 |
| T-156 | Legal pages from `legal-outline.md` with draft banner; company-details settings + footer; extend T-090 lawyer review to these pages | F19-10; `legal-outline.md` | T-150, T-111 | criterion F19-10; answer Q23 |
| T-157 | Help centre (installation, blocks/templates, start from zero, compliance, billing, uninstall) linked from F14 and the listing; blog list/post/RSS; 6 draft posts from `blog-briefs.md` | F19-12, 13 | T-152 | criteria F19-12, 13 |
| T-158 | German copy from the English master (`LLM_MODEL_COPY`), native review gate; `/de/` stays 404 until approved | F19-3; Q25 | T-152 | DE content as drafts; switch on after review |
| T-159 | In-app onboarding email sequence + uninstall reason link | F19-14; `emails.md` §3–4 | T-155 | criterion F19-14 |

| Sprint | Tickets |
| --- | --- |
| S11 | T-150, T-151, T-152, T-153, T-154 |
| S12 | T-155, T-156, T-157, T-158, T-159, then T-093 |
