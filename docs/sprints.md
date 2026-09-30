# Sprint plan and tickets

Numbering per domain (not per sprint). Sprints of 2 weeks; 6 sprints = MVP (weeks 3–14 of the plan). Only pick up a ticket once all dependencies are `done`.

## Tickets

| Ticket | Title | Spec / docs | Depends on | Status |
| --- | --- | --- | --- | --- |
| **Foundation** | | | | |
| T-001 | Repo scaffold: Django 5.2, uv, apps from 01, Docker Compose dev, Makefile, ruff/mypy/pytest, CI workflow | 00, 01 | — | ✅ done |
| T-002 | Session token validation (middleware, bounce page) + token exchange with `expiring=1` + refresh with Redis lock + `keep_tokens_fresh` + `Shop` model + Fernet | F00, 03 §2–2.3a | T-001 | ✅ done |
| T-003 | Embedded layout: App Bridge, Polaris web components, HTMX + `auth.js`, CSP middleware, i18n nl/en/de | F00, 03 §2.4–2.5, 09 | T-002 | |
| T-004 | Webhook endpoints, HMAC, dedupe, `WebhookReceipt`, dispatch task | F00, 03 §3 | T-002 | |
| T-005 | GraphQL client (throttling, errors, `get_access_token()`), `scripts/gql.py`, `.graphql` loader | 01, 03 §4–5 | T-002 | |
| T-006 | Installation tasks: shop data, metaobject/metafield definitions, log/check resolved namespace | F00, 03 §5–6 | T-005 | |
| T-007 | Price snapshot on installation + `products/update` → `PriceHistory` | F11-A, 03 §6 | T-006 | |
| **Pipeline** | | | | |
| T-010 | `GenerationJob`/`JobStep`/`AiCall`, orchestration with checkpoints, error codes, cost budget | 05 §1–2, §5 | T-005 | |
| T-011 | AI clients: Anthropic tool use + schema validation + repair attempt + cost logging | 05 §2–3, 00 | T-010 | |
| **Sources and import** | | | | |
| T-020 | Source detection via fulfillment location (`variant_locations`, `SOURCE_RULES`, storage `Shop.import_apps`) + verification of rules with `False` (06 §4.4). The onboarding screen itself belongs to T-031 | F01, 06 §4 | T-006 | |
| T-021 | Ownership guard `assert_writable` + tests on all product mutations | F01-3, 06 §3 | T-020 | |
| T-022 | Step `import` (existing, manual, URL facts) + product picker UI | F01, 05 §4.1 | T-011, T-021 | |
| **Brand and extension** | | | | |
| T-030 | BrandKit, presets, verify font list, tokens to app metafield | F05 | T-006 | |
| T-031 | Onboarding flow: steps `language`, `brand`, `sources`, `theme` (deep links + guided Mosaiq templates); step `withdrawal` as a temporary stub until T-085 | F05-1..2, 09 | T-030, T-020, T-032 | |
| T-032 | Theme App Extension scaffold, `mq-tokens` with bundled fonts, read shop metafields via `$app:mosaiq` (03 §5.3), deep links (03 §7), locales check script, uninstall behavior of blocks | F06, 04 §1, 03 §5.3, §7 | T-030 | |
| T-033 | Block `mq-page-sections` (all section types) + admin preview templates | F06-7, 09 | T-032 | |
| **Research, copy, compliance check** | | | | |
| T-012 | Step `research` + angle selection UI | F02 | T-022 | |
| T-013 | Step `copy` + guardrails + language detection + create `Page` | F03-1..5, 7 | T-012, T-087 | |
| T-080 | Claims: blocklist per language + AI check + `ClaimFinding` + score | F11-D, F11-H, 07 §4, §9 | T-013 | |
| **Images** | | | | |
| T-040 | Vertex image provider (verify model ID, Q2) + OpenAI fallback + shot plan | F04-1..2, `prompts/images.md` | T-011 | |
| T-041 | Fidelity check | F04-3 | T-040 | |
| T-042 | C2PA signing + staged upload + `fileCreate` + limit + AI label | F04-4..8, F11-12 | T-041, T-061 | |
| T-043 | Test with `c2patool`/`exiftool`: C2PA on original in Files and on `?width=800&format=webp` (Q3); update 07 §6 | F04-9 | T-042 | |
| **Pages** | | | | |
| T-050 | Steps `layout` + `publish` (draft) + GPSR check before publish + store job with child jobs | F07-1, 05 §1, §4.6 | T-013, T-033, T-042, T-080, T-082 | |
| T-051 | Page editor, rewriting, overrides, recheck/resume, set live, archive | F07-2..8 | T-050, T-080, T-061, T-083 | |
| T-052 | Save/reuse templates | F08 | T-051 | |
| T-053 | Translate into additional store languages (own metaobject entry per language, 03 §5.1) | F03-6 | T-051 | |
| **Billing** | | | | |
| T-060 | Plans, `appSubscriptionCreate`, verify return URL, status webhook (basic), access gate | F12-1..3, 08 §2–3 | T-004, T-005 | |
| T-061 | Limits + `UsageCounter` with `select_for_update` | F12-6, 08 §1 | T-060, T-010 | |
| T-062 | TrialLedger, trial reminders, upgrade/downgrade, cancellation, reconcile | F12-4..5, 7..9 | T-060 | |
| **Offers and cart** | | | | |
| T-070 | Discount Function (`cart.lines.discounts.generate.run`; volume, BOGO, gift) + config metafield test first + Function tests | F09-4, 04 §2 | T-032 | |
| T-071 | `Offer` model, editor, activate/deactivate (discount + metaobject + metafield) | F09-1..2, 5, 7 | T-070, T-083 | |
| T-072 | Block `mq-bundle-picker` + `mq-price` (price, savings, unit price, timer, stock and cut-off rules) | F09-3, 6, 8, F11-7, 04 §1 | T-071, T-083, T-081, T-087 | |
| T-073 | Embed `mq-cart-drawer` (upsells, rewards bar) | F10 | T-071 | |
| **Remaining compliance and cleanup** | | | | |
| T-081 | Omnibus: `prior_price`, `reduction`, attestation, daily metafield task | F11-A, 07 §1 | T-007 | |
| T-082 | GPSR model, form, copying, block `mq-gpsr` | F11-E, 07 §5 | T-032 | |
| T-083 | Unit price model, form, calculation | F11-B, 07 §2 | T-006 | |
| T-084 | Uninstall, `shop/redact`, export; verify what Shopify leaves behind | F13 | T-004, T-060 | |
| T-085 | Legal pages (draft templates) + `mq-withdrawal-link` + onboarding step withdrawal (checklist 07 §8.4) | F11-G, 07 §7–8 | T-032 | |
| T-088 | Withdrawal form via app proxy (two steps, `WithdrawalRequest`, confirmation email, merchant overview, GDPR webhooks) | F11-G, 07 §8.1–8.3, 02, 03 §1 and §3 | T-085, T-004 | |
| T-086 | Support page and form | F14 | T-003 | |
| T-087 | Store settings (`/app/settings/store/`): warranty policy, shipping cut-off, AI label default, stock threshold → `Shop` + app-data metafield `settings` | 09, 02 `Shop`, 03 §5.2 | T-003, T-006 | |
| **Launch** | | | | |
| T-090 | Lawyer review: templates, labels 07 §8.2 (incl. Belgium), terms, AI Act role (Q7); remove draft banner | 07, open-questions | T-085, T-088 | |
| T-091 | Evalset (30 products) + `make eval` + first report | 10 §4 | T-013, T-042 | |
| T-092 | Manual release checklist + Lighthouse | 10 §5 | all MVP | |
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
