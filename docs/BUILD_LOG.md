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
