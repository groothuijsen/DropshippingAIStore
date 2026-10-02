## 2026-10-02 — T-161/T-162: GPSR form + phase close-out + live pipeline hardening

- **T-161 GPSR form** (`/app/products/<gid>/gpsr/`): per-product GPSR entry stored in `$app:mosaiq.gpsr`; publish/go-live load it (empty metafield blocks the publish); build panel links blocked PDPs to the form.
- **T-162**: F18-6 cut-off notice in `mq-price.liquid` (nl/en/de, suppression rule); home metaobjects registered as ManagedResources + `metaobjectDelete` in Undo.
- **Live-E2E fix chain (PDP pipeline never ran against the real API)**: contract steps raise instead of fake-succeeding (`STEP_NO_OUTPUT`, `CopyInputMissing`, `PageNotFound`); copy step dumps the validated payload before section checks; images/compliance checkpoint shape fixed; AI repair messages replay the original tool_use (id preserved); OpenAI image provider uses the JSON generations endpoint (integer `n`, supported sizes, `IMAGE_MODEL_FALLBACK`); `Page.compliance_findings` added (migration 0010); `google-genai` declared.
- **Verified live**: GPSR form → metafield (API read) → PDP publish gate complete=True → compliance 100 → layout → publish → metaobject `284940402982` + ManagedResource; home metaobject MR repaired.
- mypy: config error fixed (`explicit_package_bases`) — runs end-to-end, 271 strict errors remain as burn-down.
- 1163/1163 tests.

## Unreleased

### T-160 — UI styling: WhiteNoise + Carbon Emerald theme (2026-10-02)

- **Static serving fixed**: WhiteNoise middleware + `CompressedStaticFilesStorage` in prod (CT 412 has no nginx — every `/static/*` URL 404'd and the admin ran on a 4-line inline style). `collectstatic` live; `/static/app/styles.css` verified 200 on the VPS.
- **`static/app/styles.css` — direction C "Carbon Emerald"** (user picked from a 3-way mockup: `mosaiq-ui-directions-2026-10-02.html`): near-black `#0e0f0f` surfaces, emerald `#10b981` accent, semantic CSS tokens, all 50 `mq-*` classes used by the templates (panels, forms, tables, steps, messages, lists, price advisor, cards), 44px tap targets, visible focus rings, dark scrollbars.
- **`dashboard.html` rewritten**: emoji icons removed (user rule), dead links dropped (`/app/generate/`, `/app/pages/`, `/app/offers/` — those screens are not built), cards now link only built screens (start wizard, delivery, store settings).
- **Live E2E**: app root + store settings + delivery all render `rgb(14,15,15)` with emerald accents; zero white/unstyled areas; zero emoji.
- Commits `749142a` (infra) + `3a9f2f0` (theme + dashboard).

### T-118 — Publish store (go-live) + Undo + menu placement (F15-12..14, 2026-10-02)

- `StoreBlueprint.menu_placed` + `publish_result` (migration `generator/0009`).
- `apps/generator/store_go_live.py`: `publish_collections` (resolve the Online Store publication → `publishablePublish` per blueprint collection — the only publish point for the collections created unpublished in T-117); `publish_store` (F07 go-live per eligible page; returns pages need complete `BusinessDetails` → `BUSINESS_DETAILS_MISSING`; blocked pages listed with reasons in `publish_result` + `AuditLog`); `undo_store_build` (live pages block the undo and must be archived first; otherwise `collectionDelete`/`menuDelete`/`pageDelete` + local Page archive + `ManagedResource.removed_at` + one `AuditLog` row per deletion; products and BrandKit untouched).
- Menu placement (F15-12): theme-editor deep link + "Done" checkbox (`menu_placed`); Publish/Undo sections on the build panel with blocked-page reasons. **Q20 answered** in open-questions.
- Live E2E (dev store): collection `Live geverifieerd` → **Online Store** verified read-side; shipping page `isPublished=True`; returns correctly blocked with `BUSINESS_DETAILS_MISSING`; `publish_result` stored. Undo deliberately not run live (would delete the dev store) — unit-tested.
- **Live-found + fixed**: `pageUpdate` requires `id` as a top-level argument in 2026-07 (introspection fixture `page_update_shape.json`) — Shopify `isPublished` had silently stayed false; `go_live` now aborts when the page could not be published instead of marking it live; GPSR preconditions scoped to product pages (the empty-`GpsrInfo` check blocked every standard page).
- Tests: `tests/test_t118.py` (16). 1145/1145 suite; ruff clean.

### T-117 — Store build job (12 §5/§7, F15-10, F15-15, 2026-10-02)

- `generator.ManagedResource` (migration `generator/0008`): every wizard-created Shopify resource (collection/menu/page) with gid unique per shop + title — the undo bookkeeping for T-118. `StoreBlueprint.build_job` + `store_limit_reserved_at`.
- `apps/generator/store_build.py`: the `store_build` parent job — (1) plan limits reserved in ONE transaction (`store_generations` = 1 + (n_pdps − 1), `ai_images` = n_pdps), (2) collections created **unpublished** via `collectionCreate` (real T-110 `sources` shape) + ManagedResource rows, (3) child jobs: standard pages with generated content → local `Page` + layout/publish, home from BrandKit + brief, one PDP child per selected product with the full import→research→copy→images→compliance→layout→publish pipeline (`usage_reserved` prevents double reservation), (4) menu `mosaiq-main` created LAST (FRONTPAGE + collections + pages; `menuUpdate` on re-run).
- Tasks: `run_store_build` (4-step parent, resume on failed steps, `last_error` kept, `PLAN_LIMIT_REACHED`/`BLUEPRINT_NO_PRODUCTS` error codes), `run_store_build_child`, `retry_store_build_child`, `advance_store_build` (a failed child keeps the parent running; the menu runs only when ALL children succeed).
- Build status screen: "Build my store" button with plan-usage note before start; afterwards steps (Done/Running/Error) + per-child status with Retry buttons; `build_store`/`retry_build`/`retry_child` POST actions.
- Supporting: `PAGE_TYPES_NEEDING_SHOPIFY_PAGE` += faq/shipping/returns; `JobInput.page_type` literal extended; `_reserve_usage` honors `usage_reserved`.
- **Live E2E (dev store, 2026-10-02): build GREEN** — collection `live-geverifieerd` (unpublished) + home/shipping/returns Shopify pages + `mosaiq-main` menu; parent succeeded. The run exposed a chain of pipeline code that had never executed against the real API, all fixed in `5014345`, `cf41bc9`, `8d1688f`, `cdb9e61`, `63bcea8`, the metaobject commits, `062a7fb`, `f86f00c`:
  - research/copy/import steps: `render_prompt` tuple passed as `system=` (400) + dead `model_key` values ("claude"/"sonnet" are not in MODELS);
  - `get_pending_steps` auto-created the product pipeline for standard-page children (now pre-created as SKIPPED; retry keeps them skipped);
  - GPSR gate ran for non-product pages; `error_code` varchar(60) overflow masked failures;
  - `metaobjectUpsert` query still used the pre-2026-07 shape — realigned via live introspection (deviation fixture `metaobject_upsert_shape.json`); metaobject type string corrected to `app--430212644865--page_content`; layout now writes the definition's `sections` JSON shape;
  - auto-angle selection for PDP children (no angle screen in F15); needs_input children now block the menu step.
- PDP child: import + research + auto-angle verified live; its publish step surfaces `GPSR_INCOMPLETE` until the merchant fills the GPSR form (07 §4, by design).
- Tests: `tests/test_t117.py` (26). 1129/1129 suite; ruff clean. Commits `ece5249`..`f86f00c`.

### T-116 — Standard pages faq/shipping/returns (12 §3, F15-16, F18-10, 2026-10-02)

- `PageType` += faq/shipping/returns; `StoreBlueprint.standard_pages` (migration `generator/0007`); `StandardPages`/`StandardPageContent`/`StandardFaqItem` schemas (tool `submit_standard_pages`).
- `docs/prompts/standard_pages.md`: the AI writes intro + FAQ only; hard rule — no numbers, costs, addresses or time frames outside `facts_json`.
- `apps/generator/standard_pages.py`: fact blocks from the merchant's models — shipping renders per-market days + costs from `DeliveryProfile` (no profile → "Delivery times missing" + `missing_facts`, F18-10); returns renders the 14-day withdrawal block (`/pages/withdrawal`) + address from `BusinessDetails` (D-15.4 — never invented); localized nl/en/de.
- `generate_standard_pages` task: one copy call (temp 0.4), digit guard with ONE repair round then a `verify_numbers` warning (F15-16); assembled per structure page type.
- `structure_confirm` enqueues the task; the building panel shows page content + missing-facts/verify warnings (HTMX poll until ready).
- **Related fix**: renaming a collection now cascades to menu refs — the confirm validation caught a stale-ref state live during the T-116 E2E (pre-fix blueprints need a one-time repair; dev store repaired).
- **Live E2E**: re-confirm → real AI shipping+returns content; no delivery profile on the dev shop → `missing_facts` warning shown in the panel. 1102/1102 tests; ruff clean. Commits `065e904`, `22870f3`.

### T-115 — Store structure proposal + editable tree (F15-8, 2026-10-02)

- `StoreStructure`/`CollectionPlan`/`MenuItemPlan` schemas (12 §3); tool `submit_structure`, `model_key="copy"`, temperature 0.3 per prompt header.
- `StoreBlueprint.store_structure` + `structure_error` (migration `generator/0006`); `queries/products_by_ids.graphql` (fixture captured from the dev store).
- `generate_store_structure` task: selected products → one AI call; collection GIDs outside the merchant's selection trigger ONE repair round, then a merchant-facing `structure_error` (F15-8); `select_products` now enqueues the proposal.
- Wizard structure screen: editable tree (rename, reorder, remove with floors 1 collection / 3 menu items / 2 pages, add collection from the selection, add page types); retry button on failure; confirm validates coverage, shipping+returns pages, menu refs and menu size → status `building`.
- **Live E2E**: real AI proposal (1 collection for the 1 selected product, menu of 4, shipping+returns) → confirm → `building`; rename edit live-verified after fixing `_norm_gid` (legacy webhook rows store product ids as ints — str() guard + regression test).
- 1086/1086 tests; ruff clean. Commits `c296548`, `20abff0`.

### T-114 — Product ideas + import-waiting screen + selection (F15-6/7, 2026-10-02)

- **F15-6**: `ProductIdea`/`ProductIdeas` schemas (12 §3); `generate_product_ideas` task (`model_key="research"`, temperature 0.6); `apps/generator/import_apps.py` deep links (CJ/Printify search links); wizard ideas screen (HTMX, ideas + avoid + Open-app link) and `start_import` action setting `started_products_at` (first click keeps the window).
- **F15-7**: `products_per_build` plan limits (starter 5 / pro 20 / agency 20, 12 §7); `products_list.graphql` nodes carry `createdAt`; `StoreBlueprint.imported_products` (migration `generator/0005`); the `products/create` webhook records new products on the wizard blueprint (idempotent, GID-normalized); import-waiting panel merges webhook records + a 10s fallback products query, shows vendor-based source detection and plan-max selection (1–20; Next disabled at 0, `BLUEPRINT_NO_PRODUCTS` server-side); selection advances the blueprint to `structure` (T-115's input).
- **CRITICAL webhook HMAC fix**: the receiver validated `sha256(secret + body)` instead of HMAC-SHA256 keyed with the app secret over the raw body. Every test/E2E signer used the same wrong formula, so self-signed tests passed while **every live Shopify delivery since T-110 returned 401** and no receipt was ever stored (this was also the T-131 "PriceHistory 0 rows" gap). Fixed in `apps/webhooks/hmac.py` with a regression test; test signers corrected.
- **Live E2E (dev store)**: 10 real AI ideas (Verzwaringsdeken €59–€119, Dutch) → import window → new product listed via the fallback query → selected → `status=structure`. After the HMAC fix: real `products/create` deliveries produce receipts and `imported_products` rows with full GIDs. 1065/1065 tests; ruff clean.

### T-113 — Brand step: niche_brand proposal + BrandKit prefill (2026-10-02)

- **`BrandProposal` schema** (12 §3) + **`StoreBlueprint.brand_proposal`** (migration `generator/0003`) + **`BrandKit.tagline`** (migration `themes/0002`).
- **`generate_brand_proposal` task** (Celery, F15-5): one `niche_brand` call (`model_key="copy"`, tool `submit_brand`, temperature 0.4 per prompt header) → proposal stored with F05 corrections — invalid font keys fall back to inherit (`theme`/empty), failing text-on-background contrast corrected via `validate_palette`'s suggestion (never stored as-is). No-ops when a proposal exists or the blueprint isn't in the brand state.
- **Flow**: name pick (T-112) now enqueues the brand task; the brand step (route zero) polls via HTMX while the proposal is missing, then opens the **existing BrandKit form pre-filled** (name readonly, tone/preset/palette/fonts/tagline from the proposal). Saving writes the BrandKit + tagline, stores palette/fonts on the blueprint, advances status to `ideas`, and enqueues **`sync_brand_tokens`** — the F05-5 design-token sync that was defined but never called by any save path (`themes/tasks.py`, sets `tokens_synced_at`).
- **Wizard**: ideas placeholder until T-114; presets data now carries per-preset descriptions for the prompt.
- **Live E2E (dev store)**: real AI proposal (warm/soft/lora + Dutch tagline "Maak van je avond een rustig moment") → pre-filled form verified → save → BrandKit + `bp.status=ideas` + **`tokens_synced_at` set** (real `metafieldsSet` on the dev store installation). 1038/1038 tests; ruff clean.


### T-112 — StoreBlueprint, route choice, brief + names step (2026-10-02)

- **`generator.StoreBlueprint`** (migration 0002, 12 §2.2): status state machine (brief → names → brand → …), brief fields, `name_suggestions`, `regenerate_count`, `brand_name`/`brand_slug`, later-step fields, `advance()`. **`Shop.onboarding_route`** (migration 0005): existing/zero.
- **F15-1 route choice**: onboarding brand step offers "existing brand" vs "start from zero"; zero creates a blueprint (status `brief`) and redirects to `/app/start/`; existing stores the route and waits for the BrandKit form before advancing.
- **Onboarding made reachable**: added the missing `core/onboarding/` templates (base + 6 steps) and `/app/onboarding/` URL wiring. Fixed `_get_shop` (read `request.shop_id`, which the middleware never sets → permanent 401).
- **F15-3 brief screen** (`/app/start/`): validated against the `NicheBrief` schema; nothing reaches the AI until valid.
- **F15-4 names step**: `generate_name_suggestions` task renders `niche_names.md` → `NameSuggestions` (exactly 8) → blocklist filter with one repeat call → RDAP .com check (`likely_free`/`taken`/`unknown`, 0.5 s spacing; Q21 answered: acceptable). HTMX-polled names panel; regenerate max 3; own name gets the same blocklist check.
- **`themes/brand_blocklist.py`**: geographic origins + ~180 brands + generic-claim substrings from `claims.BLOCKLIST`; rejects EcoGlow/Nike/SwissSleep.
- **AI schemas** per 12 §3: `Market`, `PriceLevel`, `NicheBrief`, `NameIdea`, `NameSuggestions`.
- **Client fixes from live E2E**: `AnthropicClient` settings fallback for the API key (systemd units don't load `.env`); names task uses `model_key="copy"`; `_make_request` drops `tool_choice`/`temperature` on 400 (claude-sonnet-5-5 rejects both) and retries once.
- **Live E2E (dev store)**: route choice → brief → 8 REAL AI names → RDAP statuses correct → panel + disclaimer + TMview → own name picked → `brand_name`/`slug`/status `brand` stored. 1020/1020 tests; ruff clean.


### T-131 — Apply price + guard + audit (2026-10-02)

- **`compliance.PriceAdvice`** model (migration 0005): inputs/advice JSON per calculation, `applied_at` + `applied_price` when the merchant applies; also normalizes `PricingSettings.markets` default to a named function (Django cannot serialize lambdas).
- **Apply flow (F17-4)**: `/app/products/<gid>/pricing/apply/` — ownership check (only `ProductSource.created_by_mosaiq`), `assert_writable(shop, gid, {"price"})` guard, `productVariantsBulkUpdate` (price only, all variants), `ShopifyUserError` handled, `PriceAdvice.applied_at` + `AuditLog(action="price_advisor_applied")`.
- **Sync-app products (F17-5)**: refused BEFORE any HTTP call; screen shows "Set this price in <app> (price rules)" + copyable advised price.
- **Advisor screen completed**: current price + difference (F17-3 remainder) and the Omnibus warning from 12 §8 when the advised price exceeds the current price (F17-6) — both deferred from T-130.
- **Live E2E (dev store)**: fresh product created via `productSet`; calc rendered €24.95 + Omnibus warning; apply wrote the price (live Admin API read: 24.95); AuditLog payload verified; `products/update` webhook was declared in `shopify.app.toml` but NOT live-registered — registered it (fixture `webhook_subscription_create_products_update.json`, args verified by introspection: `topic` + `webhookSubscription{uri,format}`); direct signed webhook test → receipt + `PriceHistory` row (24.95, source=webhook) — Omnibus chain verified end-to-end.
- 987/987 tests; ruff clean; migration 0005 applied on VPS; services restarted; healthz 200.

### T-111 — BusinessDetails, settings screen, legal template filling (2026-10-01)

- **`core.BusinessDetails`** (OneToOne Shop, 12 §2.1): legal/trade name, address, country, email, phone, company reg no, VAT id (prefix-checked against country in clean()), return address (same-as-main flag or JSON). `is_complete(purpose)` returns missing field names for `legal`/`contact`/`impressum`/`returns`; assumptions recorded in F15 spec.
- **`fill_legal_details()`** in `compliance.legal`: replaces the `[Adres]`-style placeholders (nl/en/de) from BusinessDetails; missing facts leave the placeholder visible (D-15.4: never invent business facts). Wired into `get_legal_pages()` for withdrawal, impressum and GPSR/contact.
- **`/app/settings/business/`**: GET/POST form for all fields with full_clean validation + AuditLog entry (`business_details_saved`); template with i18n labels.
- Migration 0004 applied on VPS; gunicorn + worker restarted; route verified live. 907/907 tests; ruff clean.

### T-110 complete — scope re-grant, webhook, receiver + callback fixes (2026-10-01)

- **Scope re-grant executed on dev store** (user-approved OAuth authorize): all 3 new scopes granted + verified live via accessScopes; access token refreshed → publications/publishable/menu operations now work with the stored token.
- **All T-110 fixtures live-captured** (16 success responses incl. collection_create with manual sources, publishable_publish, menu CRUD + duplicate-handle probe).
- **Q19 answered**: menuCreate auto-suffixes duplicate handles (`mosaiq-main` → `mosaiq-main-1`); no error.
- **Webhook products/create registered** on dev store (verified live). API 2026-07 deviations: `WebhookSubscriptionInput.uri` (not `address`); `WebhookSubscription.uri` directly (endpoint is a union).
- **Webhook receiver fixes**: shop_domain from `X-Shopify-Shop-Domain` header (was the HMAC header — corrupted receipts); `body_json` stored on receipt so handlers can read payloads.
- **`handle_product_create`**: initial variant-price snapshot into PriceHistory via shared idempotent `_snapshot_variant_prices()` (also used by products/update).
- **`/auth/callback` route added** (was 404): validates Shopify OAuth hmac (HEX sha256 over sorted params) → redirects to the admin app page.
- 895/895 tests passing; docs/03 "v1.1 webhook registration + receiver" section added.

### T-110 — scopes, scope check, GraphQL fixtures (2026-10-01)

- **`shopify.app.toml`**: `write_online_store_navigation` + `write_publications` scopes; `products/create` webhook topic. Note: `publications` query also needs `read_publications` — add at deploy time.
- **`apps/core/scopes.py`** (9 tests): `get_granted_scopes()` via `currentAppInstallation { accessScopes }`, `missing_scopes()`, `build_regrant_url()`, `check_start_scopes()` — safe default blocks with `SCOPE_MISSING` when the check fails.
- **Fixtures recorded live** against the dev store (AGENTS.md §5): `collection_create` (with manual sources — **Q18 answered**: selections under `inclusion`, `source.title` required), `collection_delete` (`input:` wrapped arg), `product_variants_bulk_update` (price-only verified), `inventory_item_cost`, `product_variants_by_product`, `product_create_manual`, `page_create`, `page_delete`, `publications` (access-denied state).
- **Q19 blocked**: menu/publication fixtures need the scope re-grant on the dev store (installed pre-scope-change); access-denied responses recorded as fixtures.
- **API 2026-07 deviations found**: no `MenuCreateInput` (loose args, `MenuItemCreateInput` items); `collectionDelete(input:)` vs bare-id deletes; `UserError` has no `code` field. Documented in docs/03 "v1.1 verified shapes".

### Dev store install flow — E2E verified (2026-10-01)

- **`run_on_install` completed end-to-end on the dev store**: metaobject definitions exist, all 11 metafield definitions created (`$app:mosaiq` namespace, 5 SHOP + 3 PRODUCT verified live), default shop metafields written, AuditLog `installed` entry created.
- **metaobject_reference validation shape (API 2026-07)**: option name is `metaobject_definition_type`, value is the full type string `app--<app_id>--<type>` (`6365e05`). Fixture: `tests/fixtures/shopify/metafield_validation_shape.json`.
- **Shop metafields `ownerId`**: must be `shop.shopify_gid` (Shopify GID), not the local UUID PK — httpx raised "Object of type UUID is not JSON serializable" (`b6fcf7c`).
- **Token refresh (root cause of the 401 loop)**: `keep_tokens_fresh` only selected shops on refresh-token expiry; access tokens rotate hourly and nothing refreshed them. Filter now ORs `access_token_expires_at <= now+1h`; hourly beat PeriodicTask registered via django_celery_beat (the row did not exist — beat never ran the task at all) (`9a13e0d`).

### Dev store install flow (2026-10-01; dev store `mosaiq-pod.myshopify.com`)
- Root on the app host redirects to `/app/` with all Shopify query params preserved + `frame-ancestors` CSP; `application_url` in `shopify.app.toml` now ends in `/app/` (`d50dcc0`).
- Celery app wired in `config/__init__.py` — web process no longer falls back to the RabbitMQ default broker (`47d77da`).
- Task queue routing: `CELERY_TASK_DEFAULT_QUEUE = "default"` and route key `core.tasks.*` match the worker's `-Q default,ai,shopify,low`; routing test asserts every registered task lands on a consumed queue (`d72f374`).
- `decrypt_token` accepts `memoryview` (PostgreSQL BinaryField) in addition to `bytes`/`str` (`a94e92e`).
- GraphQL shapes fixed for API 2026-07, all introspection-verified against the dev store: `MetaobjectDefinitionCreateInput` input type (`6f80474`), `fieldDefinitions[].type` as plain String (`bc81153`), `createdDefinition` payload field (`03cbdcb`), metaobject_reference metafield definitions now send `validations: [{name: metaobject_definition, value: $app:<type>}]` (`80a9575`).

### MVP complete (verified 2026-10-01; T-090 lawyer review and T-093 listing still pending)
- [T-092] Manual release checklist (`docs/release-checklist.md`) + Lighthouse check script with score/metric thresholds.
- [T-091] Evalset of 30 products (`tests/evalset/`), `make eval` target, report writer.
- [T-088] Withdrawal form via app proxy: two steps with HMAC, `WithdrawalRequest`, confirmation email, rate limiting, merchant overview.
- [T-087] Store settings screen: warranty policy, shipping cut-off, AI label default, stock threshold → `Shop` + app-data metafield.
- [T-086] Support page and contact form (F14).
- [T-085] Legal pages with draft banner, `mq-withdrawal-link` embed, onboarding withdrawal checklist step.
- [T-084] Uninstall handling, `shop/redact`, data export; Q14b metaobject-after-uninstall documented as pending dev-store check.
- [T-083] Unit price: model, merchant form, calculation, `mq-price` rendering.
- [T-082] GPSR: model, merchant form, `mq-gpsr` block, publish gate, compliance score impact.
- [T-081] Omnibus: `prior_price`, `reduction`, attestation, daily metafield sync task.
- [T-080] Claims: deterministic blocklist (nl/en/de) + AI check, `ClaimFinding`, scoring, publish gate.
- [T-073] `mq-cart-drawer` embed: upsells, rewards bar.
- [T-072] Blocks `mq-bundle-picker` + `mq-price`: price, savings, unit price, timer, stock and cut-off rules.
- [T-071] Offer model + editor with real discount create/delete via GraphQL.
- [T-070] Shopify Discount Function: volume, BOGO, free gift; config metafield; Function tests.
- [T-062] Trial ledger, reminders, upgrade/downgrade, cancellation, reconciliation.
- [T-061] Limits + `UsageCounter` reservations with `select_for_update`.
- [T-060] Billing: `Subscription`/`UsageCounter`/`TrialLedger`, `appSubscriptionCreate`, return URL, status webhook, access gate.
- [T-053] Translate page into additional store languages via own metaobject entries.
- [T-052] Save/reuse page templates.
- [T-051] Page editor: field validation, rewriting, go-live, archive.
- [T-050] Layout + publish (draft) steps, GPSR check before publish, store jobs with child jobs.
- [T-043] C2PA verification scripts (`c2patool`/`exiftool`) for Files original + CDN variants; 07 §6 updated; Q3 assumption recorded.
- [T-042] C2PA signing, staged upload, `fileCreate`, upload limit, AI label.
- [T-041] Fidelity check after image generation with retry.
- [T-040] Image providers: Vertex `gemini-3.1-flash-image` primary, escalation, OpenAI fallback; shot plan; cost table; budget guard.
- [T-033] Block `mq-page-sections` (all section types) + admin preview templates.
- [T-032] Theme App Extension scaffold, `mq-tokens` with bundled OFL fonts, deep links, locales check script.
- [T-031] Onboarding flow: language, brand, sources, theme (deep links), withdrawal step.
- [T-030] BrandKit: 6 presets, bundled fonts, contrast validation, design tokens to `$app:mosaiq` metafield.
- [T-022] Import step (existing product, manual, URL facts with robots.txt respect) + product picker UI.
- [T-021] Ownership guard `assert_writable` on all product mutations; locked-field matrix per source app.
- [T-020] Source detection from fulfillment location (`variant_locations` + `SOURCE_RULES`), `Shop.import_apps` storage.
- [T-013] Copy step: section order per page type, guardrails, language detection, SEO length validation, `Page` creation.
- [T-012] Research step with angle selection UI.
- [T-011] Anthropic client: tool use with Pydantic schema validation, one repair attempt, retry, cost logging.
- [T-010] `GenerationJob`/`JobStep`/`AiCall` models, step orchestration with checkpoints, error codes, cost budget.
- [T-007] Price snapshot on installation + `products/update` webhook → `PriceHistory`.
- [T-006] Installation tasks: shop data, metaobject/metafield definition bootstrap, default shop metafields, audit log; idempotent.

## v0.5.0 (2026-09-30)
- [T-005] GraphQL client: throttling with exponential backoff, proactive throttle waits, top-level errors, userErrors, auth errors. `.graphql` loader + `scripts/gql.py` CLI. 63/63 tests.

## v0.4.0 (2026-09-30)
- [T-004] Webhook endpoints: HMAC validation, deduplication via `WebhookReceipt`, Celery dispatch task with handlers for all Shopify topics (app/uninstalled, products/update/delete, shop/update, customers/data_request/redact, shop/redact). 45/45 tests.

## v0.3.0 (2026-09-30)
- [T-003] Embedded layout: App Bridge, Polaris web components, HTMX + auth.js (token injection), CSP frame-ancestors middleware, i18n nl/en/de, dashboard page with navigation cards. 31/31 tests.

## v0.2.0 (2026-09-30)
- [T-002] Session token validation (middleware, bounce page) + token exchange with `expiring=1` + refresh with Redis lock + `keep_tokens_fresh` beat task + `Shop`/`AuditLog` models + Fernet encryption. 20/20 tests.

## v0.1.0 (2026-09-30)
- [T-001] Repo scaffold: Django 5.2, uv, 12 apps, Docker Compose dev/prod, Makefile, ruff/mypy/pytest, CI workflow, healthcheck `/healthz`.
