# AGENTS.md — build rules for Hermes (and any other build agent)

This file is binding. Read it before every task. If this file conflicts with another document, this file wins, then `docs/00-decisions.md`, then the feature spec.

## 1. Workflow (Protocol 0 / B.L.A.S.T.)

1. Take one ticket from `docs/sprints.md`. Never work on two tickets at the same time.
2. Read the corresponding spec in `docs/specs/F##-*.md` and every document the spec references.
3. Write tests (pytest) first, based on the acceptance criteria (Given/When/Then). Make them fail.
4. Implement until the tests pass. No code outside the scope of the ticket.
5. Update the spec if you had to assume something (section "Assumptions made during build"). Also put the assumption in the PR description.
6. One PR per ticket. Title: `[T-###] short description`.

## 2. Hard prohibitions (these cause the most errors)

- **Never** use the Shopify REST Admin API. Only the GraphQL Admin API, version from `SHOPIFY_API_VERSION` (see 00-decisions).
- **Never** write theme files: no Asset API, no `themeFilesUpsert`, no `themeCreate`, no `write_themes` scope. Everything on the storefront goes through the Theme App Extension (`extensions/theme-blocks`).
- **Never** change `price`, `compareAtPrice`, `inventoryQuantity`, `sku`, `barcode` or variants on products managed by a dropship or POD app (see `docs/06-dropship-integrations.md`, ownership matrix). Mosaiq writes content only to its own metaobjects/metafields.
- **Never** render a countdown timer without a server-side `ends_at` from a real `Offer`. No timers that start or reset per visitor.
- **Never** generate or fabricate reviews, ratings, "X people are viewing now" or "Y just bought".
- **Never** show a struck-through price or discount percentage without the Omnibus calculation from `compliance.pricing.prior_price()`.
- **Never** charge fees outside the Shopify Billing API.
- **Never** put secrets in code, logs or fixtures. Store access tokens only encrypted (`core.crypto`).
- **Never** make an AI call synchronously within an HTTP request. Always via a Celery task.
- **Never** use an AI output without validation against the Pydantic schema in `docs/05-ai-pipeline.md`.
- **Never** publish images from open models (FLUX etc.) to a store. Only the providers from 00-decisions.
- **Never** store customer data (personal data of shoppers), except `WithdrawalRequest` (withdrawal form, 07 §8).

## 3. Required patterns

- Every Shopify write action is idempotent: use `metaobjectUpsert` with a fixed `handle`, or check for existence first.
- Every GraphQL response: check `userErrors` and top-level `errors`. A non-empty `userErrors` is an error, even with HTTP 200.
- Every Celery task: `acks_late=True`, explicit `max_retries`, idempotency key, writes status to `GenerationJob`/`JobStep`.
- Every webhook: validate HMAC on the raw body, deduplicate on `X-Shopify-Webhook-Id`, return 200 within 5 seconds, hand off the work to Celery.
- All texts in the UI via Django i18n (`gettext`), languages `nl`, `en`, `de`.
- Money always as `Decimal` with currency; never `float`.
- Time always timezone-aware UTC in the database.
- Language: everything in English — code, identifiers, code comments, docstrings, commit messages, PR titles and descriptions, and documentation in `docs/`. The only exceptions are user-facing strings, which live in the i18n files (`locale/` and extension `locales/`) for nl, en and de.

## 4. If something is unclear

Do not stop and do not silently guess. Choose the safest interpretation (fewest write permissions, no claims, no price display), record it under "Assumptions made during build" in the spec, and mark the PR with the label `needs-review`.

## 5. Verifying against the real API

Shopify field names can differ per API version. For every new GraphQL operation:

1. First run the operation against the dev store via `scripts/gql.py` (see `docs/01-repo-structure.md`).
2. Save the real response as a fixture in `tests/fixtures/shopify/<operation>.json`.
3. Only then adapt the client code. Tests always use the recorded fixture, never a hand-written response.

For Shopify Functions: generate the schema with `shopify app function schema` and the types with `shopify app function typegen`. Never write input queries from memory.
