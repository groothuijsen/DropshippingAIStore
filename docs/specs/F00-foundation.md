# F00 — Foundation: installation, auth, webhooks

**References:** 01, 02 (`Shop`, `WebhookReceipt`, `AuditLog`), 03 §1–4 and §6.

## Goal
A merchant can install and open the app in the Shopify admin; Mosaiq has a valid offline token, receives webhooks and has the metaobject/metafield definitions ready.

## Acceptance criteria

1. **Given** a dev store without Mosaiq, **when** the merchant installs via the Partner installation link, **then** the app opens embedded, a `Shop` exists with status `active`, an encrypted token and populated `name`, `currency_code`, `iana_timezone`, `primary_locale`.
2. **Given** an HTMX/fetch request without a session token or with an invalid one, **then** the server responds 401 with `X-Shopify-Retry-Invalid-Session-Request: 1` and no data is shown. **Given** a full page load without a valid `id_token`, **then** the server shows the bounce page (03 §2.1), which reloads with a new token.
3. **Given** a session token of shop A, **when** a request asks for data of shop B (different ID in the URL), **then** 404 (queries always filtered on `request.shop`).
4. **Given** a valid webhook with correct HMAC, **when** it arrives, **then** 200 within 5 s and one `WebhookReceipt`; the same `X-Shopify-Webhook-Id` again → 200 without a second processing.
5. **Given** a webhook with an incorrect HMAC, **then** 401 and no `WebhookReceipt`.
6. **Given** a new installation, **when** `core.tasks.on_install` has finished, **then** the metaobject definitions `$app:page_content` and `$app:offer_display` and the metafield definitions from 03 §5.2 exist; running it again produces no errors and no duplicates.
7. **Given** installation, **then** `PriceHistory` contains one `install_snapshot` row per active variant.
8. Metafield and metaobject definitions are looked up by owner type + namespace + key (or type), never by stored ID (after reinstallation they get new IDs, 03 §3).
9. Admin responses have the correct `Content-Security-Policy: frame-ancestors …` header and no `X-Frame-Options`.
10. Token exchange requests `expiring=1`; `get_access_token()` refreshes < 5 min before expiry; two concurrent tasks for the same shop refresh only once (test with two threads and a real Redis lock); a failed refresh sets `needs_reauth`.

## Out of scope
Billing (F12), onboarding content (F05/F06).

## Assumptions made during build
- **Q8 (domain):** built against the placeholder `APP_DOMAIN` from `.env` per the kickoff; later answered — the app runs on `shop.mosaiq.marketing` (salespage on `shopify.mosaiq.marketing`).
- **auth.js loading order (03 §2.4):** App Bridge loads first via `data-api-key` attribute; `auth.js` is a `type="module"` that imports HTMX dynamically and injects the session token into every HTMX request. Verified in T-003 tests.
- **Test database:** tests run on PostgreSQL (JSONField semantics), not SQLite; `CELERY_TASK_ALWAYS_EAGER = True`. CI provides a Postgres service container (BUILD_LOG item 6).
