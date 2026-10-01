# 01 — Repo structure, environment and scripts

## Directory structure (monorepo)

```
mosaiq/
├── AGENTS.md
├── README.md
├── CHANGELOG.md
├── Makefile
├── pyproject.toml            # uv, ruff, mypy, pytest config
├── uv.lock
├── shopify.app.toml          # scopes, webhooks, app proxy (source of truth)
├── package.json              # only Shopify CLI + extensions
├── docker/
│   ├── Dockerfile            # python:3.12-slim, uv sync --frozen
│   ├── compose.dev.yml
│   └── compose.prod.yml
├── config/                   # Django project
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   ├── test.py
│   │   └── prod.py
│   ├── celery.py
│   ├── urls.py
│   └── asgi.py / wsgi.py
├── apps/
│   ├── core/          # Shop, session auth, token exchange, crypto, GraphQL client
│   ├── billing/       # plans, subscriptions, limits, UsageCounter
│   ├── webhooks/      # receipt, HMAC, dedupe, dispatch to Celery
│   ├── sources/       # dropship/POD source detection, ownership rules
│   ├── generator/     # GenerationJob, JobStep, pipeline orchestration
│   ├── ai/            # provider clients, prompt loading, cost tracking, schemas
│   ├── themes/        # BrandKit, style presets, design tokens
│   ├── offers/        # bundles, cart rules, sync to Discount Function
│   ├── compliance/    # price history, Omnibus, unit price, GPSR, claims, legal pages
│   ├── templates_lib/ # saved pages/stores
│   ├── analytics/     # events (MVP: store events only)
│   └── support/       # in-app contact, status link
├── templates/                # Django templates (HTMX partials in `partials/`)
├── static/
│   ├── vendor/        # htmx.min.js, alpine.min.js (pinned versions)
│   └── app/           # own CSS/JS for the admin
├── locale/                   # nl, en, de (.po files)
├── queries/                  # GraphQL operation files (one per operation, loaded by load_query)
├── extensions/
│   ├── theme-blocks/  # Theme App Extension (Liquid, assets, locales)
│   └── bundle-discount/  # Shopify Discount Function (JS)
├── scripts/
│   ├── gql.py         # run GraphQL against dev store (load_query by name)
│   ├── check_locales.py  # verify nl/en/de locale coverage
│   ├── lighthouse_check.py  # Lighthouse audit with thresholds (T-092)
│   └── verify_c2pa.py     # C2PA/exiftool verification (T-043)
├── tests/
│   ├── fixtures/shopify/   # recorded GraphQL responses
│   ├── fixtures/ai/        # recorded AI responses
│   ├── evalset/            # 30 test products (JSON)
│   └── <per app>/
└── docs/
```

## Environment variables

All variables are in `.env.example` with empty or dummy values. `.env` is in `.gitignore`.

| Variable | Required | Example / explanation |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | yes | `config.settings.prod` |
| `DJANGO_SECRET_KEY` | yes | 50+ characters |
| `DJANGO_ALLOWED_HOSTS` | yes | `app.mosaiq.<domain>` |
| `APP_URL` | yes | `https://app.mosaiq.<domain>` (no trailing slash) |
| `DATABASE_URL` | yes | `postgres://mosaiq:***@db-01:5432/mosaiq` |
| `REDIS_URL` | yes | `redis://db-01:6379/0` |
| `FERNET_KEYS` | yes | comma-separated Fernet keys, first is active |
| `SHOPIFY_API_KEY` | yes | client ID from Partner Dashboard |
| `SHOPIFY_API_SECRET` | yes | client secret |
| `SHOPIFY_API_VERSION` | yes | `2026-07` |
| `SHOPIFY_BILLING_TEST` | yes | `true` in dev/staging, `false` in prod |
| `SHOPIFY_DISCOUNT_FUNCTION_HANDLE` | yes | `bundle-discount` |
| `ANTHROPIC_API_KEY` | yes | |
| `LLM_MODEL_RESEARCH` / `LLM_MODEL_COPY` / `LLM_MODEL_CHECK` | yes | see 00-decisions |
| `GOOGLE_CLOUD_PROJECT` | yes | Vertex AI project |
| `GOOGLE_CLOUD_LOCATION` | yes | `eu` (multi-region endpoint `aiplatform.eu.rep.googleapis.com`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | yes | path to service account JSON (outside the repo) |
| `IMAGE_MODEL_PRIMARY` | yes | `gemini-3.1-flash-image` |
| `IMAGE_MODEL_ESCALATE` | yes | `gemini-3-pro-image` |
| `OPENAI_API_KEY` | yes | image fallback |
| `IMAGE_MODEL_FALLBACK` | yes | `gpt-image-2.5-sunburst` |
| `OPENAI_BASE_URL` | no | `https://eu.api.openai.com/v1` once EU residency is approved |
| `C2PA_SIGNING_CERT_PATH` / `C2PA_SIGNING_KEY_PATH` | yes | certificate for own C2PA manifest |
| `EMAIL_URL` | yes | SMTP for transactional emails (trial, cancellation) |
| `SENTRY_DSN` | no | GlitchTip DSN |
| `AI_COST_ALERT_USD_PER_STORE` | no | default `1.00` |

## Makefile targets

| Target | Does |
| --- | --- |
| `make dev` | `docker compose -f docker/compose.dev.yml up` (web, worker, beat, postgres, redis) |
| `make test` | `uv run pytest -q --cov` |
| `make lint` | `uv run ruff check . && uv run ruff format --check . && uv run mypy apps` |
| `make migrate` | `uv run python manage.py migrate` |
| `make messages` | `makemessages -l nl -l en -l de` and `compilemessages` |
| `make ext-dev` | `npx shopify app dev` (tunnel + extensions live in dev store) |
| `make ext-deploy` | `npx shopify app deploy` (new app version with extensions) |
| `make eval` | `uv run python tests/evalset/run_eval.py` |

## `scripts/gql.py` (mandatory for every new GraphQL operation)

- Usage: `uv run python scripts/gql.py <query-name> --shop <dev-store>.myshopify.com --token <offline-token>` (optional JSON variables as second positional argument; `--version` defaults to `SHOPIFY_API_VERSION` / `2026-07`).
- Loads `<query-name>.graphql` from the repo-root `queries/` directory (via `load_query`), runs it against the shop, prints the response.
- Fails with exit code 1 on any exception. Record the real response as a fixture in `tests/fixtures/shopify/<operation>.json` (AGENTS.md §5).

## GraphQL files

- Each operation lives in its own `.graphql` file in the repo-root `queries/` directory (loaded by `load_query` in `apps/core/shopify_client.py`). No inline query strings in Python.
- The client (`apps/core/shopify_client.py`) loads files by name, matching the names in 03 §5: `client.execute("product_create_manual", variables)`.
