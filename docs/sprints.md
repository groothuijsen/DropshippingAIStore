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
| T-131 | Apply price for writable products + guard tests for sync-app products + audit log | F17-4..5 | T-130, T-021 | criteria F17-4..5 |
| **Start from zero (F15)** | | | | |
| T-112 | `StoreBlueprint` model + route choice in onboarding `brand` + brief screen + names step (prompt `niche_names`, blocklists, RDAP check, TMview link, regenerate) | F15-1, 3, 4; 12 §2.2 | T-110 | criteria F15-1, 3, 4; answer Q21 |
| T-113 | Brand step (prompt `niche_brand`) → existing BrandKit form | F15-5 | T-112, T-030 | criteria F15-5 |
| T-114 | Product ideas (prompt `product_ideas`) + import-waiting screen (webhook + poll) + selection | F15-6, 7 | T-113 | criteria F15-6, 7 |
| T-115 | Structure proposal (prompt `store_structure`) + editable tree | F15-8 | T-114 | criteria F15-8 |
| T-116 | Page types `faq`, `shipping`, `returns`: schemas, section rules, fact blocks from models, `mq-page-sections` rendering | 12 §3, F15-16, F18-10 | T-111, T-140, T-050 | criteria F15-16, F18-10 |
| T-117 | `store_build` job: limit reservation, collections, page/PDP child jobs, menu, `ManagedResource`, status screen, retry, idempotency | F15-10, 11, 15; 12 §5, §7 | T-115, T-116 | criteria F15-10, 11, 15 |
| T-118 | Menu placement step + "Publish store" (go-live + collection publish) + Undo | F15-12..14 | T-117 | criteria F15-12..14; answer Q20 |
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
