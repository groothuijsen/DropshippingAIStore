# BUILD_LOG.md — Mosaiq Build Orientation

## Architecture Summary

Mosaiq is a Shopify public embedded app (Django 5.2, Python 3.12) that turns any product into a complete, EU-compliant store. **Auth:** Shopify managed installation with token exchange (session token → expiring offline access token, 1h validity, 90-day refresh token with Redis-locked refresh). **Pipeline:** 7-step Celery chain (import → research → copy → images → compliance_check → layout → publish), each step checkpoints output in `JobStep.output` for restart resilience. Store jobs run import+research once, then spawn 3 child jobs (home, pdp, about) from copy onward. **Storefront:** Theme App Extension only (no custom theme, App Store requirement 5.1.1). Blocks: `mq-page-sections` (all section types), `mq-bundle-picker`, `mq-price`, `mq-gpsr`. Embeds: `mq-tokens` (CSS variables + bundled OFL fonts), `mq-cart-drawer`, `mq-withdrawal-link`. All storefront data via `$app:mosaiq` metafields/metaobjects. **Discounts:** Shopify Discount Function (`cart.lines.discounts.generate.run`) for volume/BOGO/free_gift; config as JSON metafield on the discount. **Compliance:** Omnibus prior price algorithm, GPSR per product, unit price, deterministic claim blocklist + AI check, withdrawal guest form via app proxy (DE requirement), C2PA signing for AI images. **Billing:** Shopify Billing API, 3 plans ($29/$59/$149), 7-day trial, limits reserved at job start via `select_for_update`. **AI:** Anthropic for text (tool use with Pydantic schemas), Vertex AI for images (gemini-3.1-flash-image primary, gemini-3-pro-image escalation, gpt-image-2.5-sunburst fallback), all calls async via Celery.

## Contradictions, Gaps and Ambiguities

### 1. Domain name not decided (Q8)
- **Files:** open-questions.md Q8, 01-repo-structure.md (`APP_URL`, `DJANGO_ALLOWED_HOSTS`)
- **Impact:** Blocks T-001 (repo scaffold needs `APP_DOMAIN` in `.env.example`). Kickoff.md says "use `APP_DOMAIN` from .env with placeholder `app.mosaiq.example` and continue" — I will follow this.

### 2. auth.js loading order ambiguity
- **File:** 03-shopify-integration.md §2.4
- **Issue:** The doc says "HTMX is therefore not included as a separate `<script>` in the template" and that auth.js loads HTMX dynamically via `import()`. But the template must load App Bridge first (`<script src="https://cdn.shopify.com/shopifycloud/app-bridge.js">`), then auth.js as `type="module"`. The exact sequence and whether `shopify` global is available when auth.js runs needs verification in T-003.

### 3. Image resolution per slot not in 00-decisions
- **Files:** 05-ai-pipeline.md §4.4 says "2K for hero/lifestyle_*, 1K for detail_*"; 00-decisions lists model/size but not per-slot resolution mapping.
- **Impact:** Code needs a slot→size mapping. Will implement per 05 §4.4 and record as assumption.

### 4. EMPCO_GENERIC NL rule is natural language, not regex
- **File:** 07-compliance.md §4.1
- **Issue:** The NL column says "groen (als bijvoeglijk nw. bij product)" — this means "groen" only when used as an adjective describing the product, not as a noun (e.g. "groente" = vegetable). The code needs word boundary matching + POS context or a simpler heuristic (e.g. "groen" not followed by "e" to avoid "groente"). Will implement as word boundary + exclusion list and record assumption.

### 5. SOURCE_RULES Printify handle is inferred (Q17)
- **File:** 06-dropship-integrations.md §4.3, open-questions.md Q17
- **Issue:** Printify fulfillment handle `^printify$` is marked `False` (not confirmed). CJ, AutoDS, Zendrop handles also unconfirmed.
- **Impact:** Blocks T-020 verification. Kickoff says "not blocking: onboarding question covers it." Will proceed with onboarding fallback.

### 6. Test Postgres requirement
- **File:** 10-testing.md §1
- **Issue:** Tests require Postgres (not SQLite) for JSONField behavior. Docker Compose for tests needs a Postgres service. `CELERY_TASK_ALWAYS_EAGER = True`.
- **Impact:** CI workflow needs Postgres service container.

### 7. `Page.sections` merge logic for translation
- **Files:** 02-data-model.md (`Page.sections`), F03-6, 05 §4.3
- **Issue:** Copy step creates `Page` with `sections = {content_locale: payload}`. Translate step adds `sections[<lang>] = new_payload`. The merge must not overwrite existing languages. Clear in spec but needs careful implementation.

### 8. File reference format for metaobject images
- **Files:** 03-shopify-integration.md §5.1 (`image_hero` = `file_reference`), 05 §4.4 (staged upload + fileCreate)
- **Issue:** After `fileCreate`, the response returns a `File` with `id` (GID). The metaobject field `file_reference` expects a GID like `gid://shopify/File/123`. Need to verify this works with metaobject `metaobjectUpsert`.

### 9. `compare_at_price` display vs Omnibus
- **Files:** 04-extensions.md §1, 07-compliance.md §1.3
- **Issue:** The doc says "Show the variant's struck-through compare_at_price only via mq-price and only if prior_price exists." But `compare_at_price` is a Shopify field that the theme may already render. Mosaiq cannot suppress the theme's own rendering. The doc acknowledges this: "Show the merchant a warning if their theme itself displays a compare-at price."
- **Impact:** Minor UX issue; will implement the warning.

### 10. Celery queue routing not fully specified
- **File:** 00-decisions.md (queues: default, ai, shopify, low), 05-ai-pipeline.md §1 (per-step queues)
- **Issue:** The pipeline doc assigns queues per step, but the beat tasks (daily snapshot, reconcile, keep_tokens_fresh) are not assigned. Will default beat tasks to `low` queue.

## Open Questions Blocking Tickets

| Question | Blocks | Resolution per kickoff |
| --- | --- | --- |
| Q8 (Domain) | T-001 | Use placeholder `app.mosaiq.example` from `.env` |
| Q7 (Lawyer review) | T-090 | Build per spec, mark `needs-review` |
| Q12b (Vertex EU endpoint) | T-040 | Verify in T-040; if not available, use `global` + note |
| Q15 (OpenAI EU residency) | fallback, not blocking | Continue without; apply for approval separately |
| Q16 (Belgium withdrawal) | T-090 | Follow directive text, lawyer confirms |
| Q17 (Dropship handles) | T-020 | Not blocking: onboarding question covers it |
| Q3 (C2PA on CDN) | T-043 | Not blocking: SynthID + label cover it |
| Q14b (Metaobject after uninstall) | T-084 | Test in dev store, document |

## Ready to Start

All docs read. T-001 has no blocking dependencies (Q8 resolved via placeholder). Sprint 1 tickets: T-001 through T-007. Awaiting confirmation before starting T-001.

---

# 2026-10-01 — v1.1/v1.2 catch-up (kickoff from kickoff-v1.1.md)

Docs read: AGENTS.md, README, docs/12, docs/13, specs F15–F19, prompts
{niche_names, niche_brand, product_ideas, store_structure, edit_page},
docs/marketing/ (all 8 files), sprints.md v1.1/v1.2 sections,
open-questions.md. Code compared against them on branch `main` at `9ac3ea3`.

## A. Contradictions between the new docs and the existing code/docs

### A1. Plan prices: 00-decisions.md vs apps/billing/plans.py (BLOCKS T-153, claim C-23)
- **Files:** `docs/00-decisions.md` §pricing table; `apps/billing/plans.py` `PLAN_PRICES`;
  `docs/marketing/claims.md` C-23; old architecture summary above ("3 plans ($29/$59/$149)").
- **Issue:** 00-decisions and claims.md C-23 say Starter USD 29 / Pro **59** / Agency **149**
  (annual 290/590/1490). `plans.py` (T-060, commit 4af393e, 17:42) has Starter 29 / Pro **79**
  / Agency **199** (annual 290/790/1990). The spec predates the code by ~9 h the same day.
- **Impact:** F19-4 renders the pricing table from `plans.py`; C-23 claims "$29/$59/$149".
  Precedence (AGENTS.md > 00-decisions) says the code is wrong, but the later commit may
  reflect a deliberate price change that never reached the docs. Money question → **Paul decides**.
- **Not fixed by Hermes.** T-153 and the C-23 verification stay blocked until answered.

### A2. Q8 listed as both open and answered (docs/open-questions.md)
- **File:** `docs/open-questions.md` — "Still open" table still lists Q8 (app domain,
  blocks T-001, owner Paul) while the v1.2 section states "Q8 is answered: app on
  shop.mosaiq.marketing, marketing site on shopify.mosaiq.marketing."
- **Resolution per reality:** Q8 IS answered (both subdomains deployed and live since
  2026-10-01). The "Still open" row is stale; the old BUILD_LOG Q8 entry above is stale too.
- **Fix:** move Q8 to Answered in open-questions.md (one-line edit, done in the next
  bookkeeping pass — not committed here to keep this catch-up read-only in spirit).

### A3. sprints.md status column and CHANGELOG.md are stale for T-006 … T-092
- **Files:** `docs/sprints.md` (only T-001–T-005 marked ✅), `CHANGELOG.md` (ends at T-005).
- **Reality:** test files exist and pass for T-006, T-007, T-010–T-013, T-020–T-022,
  T-030–T-033, T-040–T-043, T-050–T-053, T-060–T-062, T-070–T-073, T-080–T-088, T-091, T-092
  (863 tests green, 0 failed). Memory confirms sprints 1–6 complete + T-087 + pipeline phases.
- **Impact:** bookkeeping only — but the kickoff's "finish open MVP tickets first" step
  cannot be done from sprints.md alone. A verification pass per ticket (criteria vs code)
  is required before marking done; DoD also demands spec assumption sections filled in,
  which **no** spec has yet (all still "_(to be filled in by Hermes)_").

### A4. Spec "Assumptions made during build" empty in every spec (F00–F19)
- **Files:** all 20 files in `docs/specs/`.
- **Issue:** README DoD requires "Spec updated (assumptions)"; every completed MVP ticket
  left the section as the placeholder. Violation of the per-ticket loop for T-006+.
- **Impact:** audit trail gap. Backfill during the per-ticket verification pass (A3).

### A5. mypy does not run at all (pre-existing)
- **Repro:** `uv run mypy apps` → "Source file found twice under different module names:
  core.models and apps.core.models" (1 error, checking aborted).
- **Impact:** README DoD ("mypy without new errors") is unverifiable. Needs a mypy config
  fix (`explicit_package_bases` / `mypy_path`) — small ticket-sized chore, not done here.

### A6. docs/12 + prompts reference `themes/…` but the package is `apps/themes/`
- **Files:** docs/12 §3 (font_heading "key from themes/fonts.py"), §8
  (`themes/brand_blocklist.py`), docs/prompts/niche_brand.md (`themes/fonts.py`,
  `themes/presets.py`).
- **Reality:** `apps/themes/fonts.py` and `apps/themes/presets.py` exist;
  `apps/themes/brand_blocklist.py` does NOT exist yet (expected in T-112: "top 500 consumer
  brands, maintained as data"). Path in docs is shorthand, not a real gap — except the
  blocklist file, which T-112 must create.

### A7. v1.1 models/schemas referenced by docs do not exist yet (expected, not a defect)
- Confirmed absent: `core.BusinessDetails`, `generator.StoreBlueprint`,
  `generator.ManagedResource`, `generator.PageEdit`, `compliance.DeliveryProfile`,
  `compliance.DeliveryOverride`, `compliance.PricingSettings`, `compliance.PriceAdvice`,
  `compliance/vat_rates.py`; AI schemas `NicheBrief`, `NameSuggestions`, `BrandProposal`,
  `ProductIdea(s)`, `CollectionPlan`, `MenuItemPlan`, `StoreStructure`, `EditOp`,
  `PageEditResult`; `Shop.onboarding_route`; `Page.page_type` choices `faq/shipping/returns`;
  `JobKind.store_build`; `UsageCounter.page_edits`. All are T-110…T-142 deliverables.
  (`Section` union and `PaletteSuggestion` DO exist in apps/ai/schemas.py — good.)

### A8. Shopify additions from docs/12 §4 not in shopify.app.toml yet (expected)
- Missing until T-110: scopes `write_online_store_navigation` + `write_publications`;
  webhook `products/create`; operations collection_create/publications/publishable_publish/
  menu_*/collection_delete/page_delete/product_variants_bulk_update/inventory_item_cost.
  Current toml (commit 88b28d5) matches the MVP scope list exactly.

### A9. Current salespage carries the exact claims docs/13 §1 flags (known; F19 replaces it)
- `templates/marketing/shopify_salespage.html` (live on shopify.mosaiq.marketing):
  (1) "researches products" wording, (2) "never stores personal data of your shoppers"
  (false — WithdrawalRequest, 07 §8), (3) FAQ "any plan that supports … custom app
  installs" (it is a public App Store app), (4) Google Fonts from fonts.googleapis.com
  (GDPR, LG München I 3 O 17493/20 — must be self-hosted), (5) English only, no pricing,
  no legal pages, no sitemap/hreflang. docs/13 already lists all five; T-150…T-158 fix them.
  The page stays live until T-150 replaces it with `apps/marketing`.

### A10. webhooks/0002_add_body_json.py has no doc counterpart
- The committed migration adds `WebhookReceipt.body_json` (parsed body storage). No section
  in 02-data-model.md mentions it. Harmless; add a line to 02 during bookkeeping.

## B. MVP ticket status (evidence-based, per kickoff order "up to T-092")

| Status | Tickets |
| --- | --- |
| Marked done in sprints.md + CHANGELOG | T-001 – T-005 |
| Built + tests green, NOT marked (A3/A4 bookkeeping missing) | T-006, T-007, T-010–T-013, T-020–T-022, T-030–T-033, T-040–T-043, T-050–T-053, T-060–T-062, T-070–T-073, T-080–T-088, T-091, T-092 |
| Genuinely open — external dependency | T-090 (lawyer: Q7, Q16; draft banner still in apps/compliance/legal.py) |
| Genuinely open — external dependency | T-093 (App Store listing; now also depends on T-156 privacy URL per sprints v1.2 note) |

Coverage (DoD ≥ 80%): generator 82.9%, billing 87.2%, offers 92.3%, compliance 84.3% — all pass.
Evalset: 30 products present (`tests/evalset/eval_products.json`), `make eval` target exists.
**Conclusion:** the MVP is code-complete except T-090/T-093; what remains is a per-ticket
verification + marking pass (sprints.md, CHANGELOG lines T-006+, spec assumptions) before
v1.1 work starts. The kickoff forbids assuming: each ticket's Given/When/Then must be
checked against its tests before it is marked ✅.

## C. Open questions Q8–Q25 → tickets they block

| # | Blocks | Owner | State |
| --- | --- | --- | --- |
| Q3 | T-043 (not blocking: SynthID + label cover) | Hermes | open |
| Q7 | T-090 (launch) | Paul + lawyer | open |
| Q8 | — (was T-001) | — | **answered** (stale row, A2) |
| Q12b | T-040 | Hermes | open |
| Q15 | fallback only, not blocking | Paul | open |
| Q16 | T-090 | lawyer | open |
| Q17 | T-020 (not blocking: onboarding question covers) | Hermes | open |
| Q14b | T-084 | Hermes | open |
| Q18 | T-117 | Hermes (fixture) | open |
| Q19 | T-117 | Hermes (fixture) | open |
| Q20 | T-118 | Hermes | open |
| Q21 | T-112 | Hermes | open |
| Q22 | T-151 | Paul | open |
| Q23 | T-156 | Paul | open |
| Q24 | T-155 | Paul | open |
| Q25 | T-158 | Paul | open |
| **A1 new** | T-153 + claim C-23 | **Paul** | open (price table $59/$149 vs $79/$199) |

## Ready to Start

Catch-up complete, read-only. Awaiting Paul's confirmation per kickoff §1.4.
First actions after confirmation: per-ticket MVP verification/marking pass (B), then
lowest v1.1 ticket with done dependencies (T-110, blocked only by T-092 verification;
Q18–Q21 get answered inside T-110/T-112/T-117/T-118 as fixtures). A1 (prices) and
Q22–Q25 need Paul before their tickets.
