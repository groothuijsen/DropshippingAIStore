# Mosaiq — build documentation

Mosaiq is an embedded Shopify app that turns a product into a complete, own-brand and EU-compliant store: AI research, copy, images, pages, bundles and cart drawer. Strategy, market and GAP analysis are in the plan document (Claude Doc "Atlas-kloon: PRD, SOP & Go-to-Market"). This folder is the **build specification**: exactly what is built and how.

## Reading order

| # | File | Purpose |
| --- | --- | --- |
| 1 | `AGENTS.md` | Binding build rules and prohibitions. Always first. |
| 2 | `docs/00-decisions.md` | Recorded choices: versions, libraries, models, names |
| 3 | `docs/01-repo-structure.md` | Folders, env variables, Docker, scripts |
| 4 | `docs/02-data-model.md` | All Django models, fields, constraints |
| 5 | `docs/03-shopify-integration.md` | Auth, webhooks, scopes, GraphQL operations, metaobjects |
| 6 | `docs/04-extensions.md` | Theme App Extension blocks and Discount Function |
| 7 | `docs/05-ai-pipeline.md` | Pipeline steps, statuses, Pydantic schemas |
| 8 | `docs/prompts/` | Prompts per step (research, copy, images, compliance_check, guardrails, url_facts, palette, rewrite); target language is a variable |
| 9 | `docs/06-dropship-integrations.md` | DSers, CJ, Zendrop, AutoDS, Printify: detection and ownership rules |
| 10 | `docs/07-compliance.md` | Omnibus, unit price, timers, GPSR, EmpCo, AI Act, withdrawal as algorithms |
| 11 | `docs/08-billing.md` | Plans, limits, trial, cancellation |
| 12 | `docs/09-ui-screens.md` | Screens, routes, HTMX partials |
| 13 | `docs/10-testing.md` | Test setup, fixtures, evalset, manual checklist |
| 14 | `docs/11-ops-deploy.md` | Proxmox, Docker Compose, CI, backups, monitoring |
| 15 | `docs/specs/` | One spec per feature with acceptance criteria |
| 16 | `docs/sprints.md` | Tickets, order, dependencies |
| 17 | `docs/open-questions.md` | What has not been decided yet and who decides |

## MVP scope (v1.0)

Features F01–F14 from `docs/specs/`. Languages: NL, EN, DE. The withdrawal form (guest, without login) is in the MVP because of the German requirements (07 §8.1). Demo niches: wellness/sleep, car accessories, POD merch.

**Not in MVP:** product research, own checkout, subscriptions engine, catalogs > 10 products, CSV/bulk, A/B test (v1.1), analytics dashboard (v1.1), style editor (v1.1), BYOK (v1.2+).

## Definition of done (every ticket)

- Tests green (`make test`), coverage ≥ 80% on `generator/`, `billing/`, `offers/`, `compliance/`.
- `ruff check` and `ruff format --check` clean; `mypy` without new errors.
- Spec updated (assumptions), changelog line in `CHANGELOG.md`.
- Manually tested in the dev store on Dawn and Horizon if the ticket touches the storefront.
- No new Shopify scope without updating `docs/03-shopify-integration.md` and the App Store listing.
