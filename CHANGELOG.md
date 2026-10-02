## Unreleased

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
