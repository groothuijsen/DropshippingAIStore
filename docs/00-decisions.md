# 00 — Locked decisions

Do not change anything in this file without Paul's explicit permission. If something is not listed here, the safest choice applies (see AGENTS.md §4).

## Runtime and libraries

| Component | Choice | Version / pin |
| --- | --- | --- |
| Language | Python | 3.12 |
| Package manager | `uv` with `uv.lock` in the repo | latest stable |
| Web framework | Django | 5.2 LTS |
| ASGI/WSGI server | Gunicorn with Uvicorn workers | latest stable |
| Database | PostgreSQL | 16 |
| Cache + broker | Redis | 7 |
| Task queue | **Celery 5.x** (not Dramatiq) with `django-celery-beat` for periodic tasks | latest 5.x |
| HTTP client | `httpx` (sync in Celery tasks, timeout always explicit) | latest |
| Validation | Pydantic v2 | latest 2.x |
| JWT | `PyJWT` | latest |
| Encryption | `cryptography` (Fernet), key from env `FERNET_KEYS` (comma-separated, first = active, rotation possible) | latest |
| Config | `django-environ` | latest |
| Frontend admin | HTMX 2.x + Alpine.js 3.x, loaded from own static files (no CDN except Shopify) | pinned in `static/vendor/` |
| Shopify UI | App Bridge (`https://cdn.shopify.com/shopifycloud/app-bridge.js`) + Polaris web components (`https://cdn.shopify.com/shopifycloud/polaris.js`). Verify both URLs in the Shopify docs during T-003 | hosted by Shopify |
| Tests | `pytest`, `pytest-django`, `pytest-socket`, `factory_boy`, `respx` (httpx mocks), `freezegun` | latest |
| Language detection | `langdetect` (with fixed `DetectorFactory.seed = 0`) | latest |
| Lint/format | `ruff` (lint + format), `mypy` with `django-stubs` | latest |
| Extensions | Shopify CLI 3.x (Node 20 LTS), Functions in **JavaScript** (template `vanilla-js`), not Rust | latest 3.x |
| C2PA | `c2pa-python` | ≥ 0.37 |
| Errors | GlitchTip (Sentry-compatible), `sentry-sdk` in Django and Celery | latest |

## Shopify

| Topic | Choice |
| --- | --- |
| API | GraphQL Admin API only |
| API version | `2026-07` (env `SHOPIFY_API_VERSION`). Upgrade only via a separate ticket |
| App type | Public app, embedded, distributed via the App Store |
| Auth | Shopify managed installation + token exchange (session token → offline access token). No authorization code flow |
| Configuration | `shopify.app.toml` is the source for scopes, webhooks, app proxy and extensions |
| App handle | `mosaiq` |
| Metafield namespace | `$app:mosaiq` (app-reserved) |
| Metaobject types | prefix `$app:` (see `03-shopify-integration.md`) |
| Billing | Shopify Billing API (`appSubscriptionCreate`), currency USD |
| Theme | Never write to it and no custom theme (App Store requirement 1.1.3/5.1.1). Theme app extension + templates `product.mosaiq`/`page.mosaiq` created by the merchant in the theme editor (09) |
| Offline tokens | Expiring (`expiring=1`), mandatory for public apps since April 1, 2026; refresh with a Redis lock (03 §2.3a) |

## AI providers

| Purpose | Provider | Model (env variable) | Default value |
| --- | --- | --- | --- |
| Research (step 2) | Anthropic API | `LLM_MODEL_RESEARCH` | `claude-sonnet-5-5` |
| Copy per section (step 3) | Anthropic API | `LLM_MODEL_COPY` | `claude-sonnet-5-5` |
| Copy compliance check | Anthropic API | `LLM_MODEL_CHECK` | `claude-haiku-4-5-20251001` |
| Images primary | Google Vertex AI, EU multi-region endpoint (`location=eu`, `https://aiplatform.eu.rep.googleapis.com`) | `IMAGE_MODEL_PRIMARY` | `gemini-3.1-flash-image` (GA) |
| Images escalation (fidelity) | Google Vertex AI, same as above | `IMAGE_MODEL_ESCALATE` | `gemini-3-pro-image` |
| Images fallback (provider error) | OpenAI API, EU residency `https://eu.api.openai.com` (requires approval; until then the standard endpoint) | `IMAGE_MODEL_FALLBACK` | `gpt-image-2.5-sunburst` |

- Use model IDs without `-preview`; the preview versions of the Gemini image models have been shut down. Before T-040, verify in the Vertex Model Garden that `gemini-3.1-flash-image` is available on `location=eu`; if not, use `global` and record this in `open-questions.md` (consequence for data residency).
- Structured output with Anthropic via **tool use**: one tool per step with `input_schema` = the JSON schema of the Pydantic model, and `tool_choice` forced to that tool.
- Temperature: research 0.4, copy 0.7, check 0.
- Every AI call logs: provider, model, input tokens, output tokens, cost (USD, `Decimal`), duration, job step ID.

## Languages, time and money

- UI languages: `nl`, `en`, `de`. Source: the query parameter `locale` that Shopify sends when loading the app (03 §2.1); fallback `shop.primaryLocale`, then `en`.
- Content languages MVP: `nl`, `en`, `de`. A store has one primary content language; additional languages as a separate metaobject entry per language (03 §5.1, F03-6).
- Database: UTC. Display: the shop's time zone (`shop.ianaTimezone`).
- Money: `Decimal` + ISO 4217 currency. Round to 2 decimals with `ROUND_HALF_UP`, except discount percentages (always round **down**, see 07-compliance).

## Naming

- Django apps: `core`, `billing`, `webhooks`, `generator`, `ai`, `themes`, `offers`, `compliance`, `sources`, `templates_lib`, `analytics`, `support`.
- Celery queues: `default`, `ai` (AI calls), `shopify` (Admin API write actions), `low` (cleanup, snapshots).
- Task names: `<app>.tasks.<verb>_<object>`, e.g. `generator.tasks.run_research_step`.
- Ticket IDs: `T-###`. Feature IDs: `F##`.

## Pricing (plans)

| Plan key | Name | Price/30 days | Annual |
| --- | --- | --- | --- |
| `starter` | Starter | USD 29.00 | USD 290.00 |
| `pro` | Pro | USD 59.00 | USD 590.00 |
| `agency` | Agency | USD 149.00 | USD 1490.00 |

Trial: 7 days. Limits are defined in `docs/08-billing.md`.

## v1.1 additions

See `docs/12-v1.1-store-builder.md` §1 (decisions D-15.1 to D-18.1). That document takes precedence for F15–F18.
