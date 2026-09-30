# F13 — Uninstall, cleanup and GDPR

**References:** 03 §3, 02 (CASCADE conventions), 08 §4–5.

## Acceptance criteria

1. `app/uninstalled`: `Shop.status = uninstalled`, running jobs `cancelled` (Celery revoke), token wiped, confirmation email sent, event `uninstalled`.
2. After uninstall Mosaiq makes **no** more Admin API calls (token is invalid); tasks that would still do so stop silently with a log line.
3. On uninstall Shopify itself removes the app blocks from the theme and the app metafield definitions; Shopify retains the values for an unknown period and reattaches them on reinstallation (03 §3). T-084 records with a test in the dev store what remains of metaobjects (Q14b) and documents that in the privacy statement.
4. Reinstallation within 48 hours: the existing `Shop` is reactivated, new token, data retained.
5. `shop/redact`: all rows of the shop deleted (test counts rows per model before/after); `TrialLedger` remains. If the shop has meanwhile been reinstalled (`status = active`, `installed_at` > `uninstalled_at`), the redact is ignored and logged.
6. `customers/data_request` and `customers/redact`: handling of `WithdrawalRequest` rows according to 03 §3; Mosaiq does not store any other shopper data.
7. There is a data export for the merchant (JSON of pages, offers, BrandKit) via Settings, so they can take their content with them.

## Assumptions made during build
_(to be filled in by Hermes)_
