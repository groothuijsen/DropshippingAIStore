## Unreleased

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
