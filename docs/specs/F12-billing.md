# F12 — Billing

**References:** 08 (complete), 02 (`Subscription`, `UsageCounter`, `TrialLedger`), 03 §3 (`app_subscriptions/update`).

## Acceptance criteria

1. Without an active subscription, generation, publishing and offers are not available; onboarding and settings are.
2. Choose plan → `appSubscriptionCreate` with correct price, interval, `trialDays`, `test`; redirect to `confirmationUrl` outside the iframe.
3. After approval the merchant returns to `/app/billing/return/` in the embedded app; status `active`.
4. Second installation on the same domain → `trialDays = 0`.
5. 48 hours before trial end: email + banner with one-click cancellation.
6. Limits according to 08 §1 with reservation at job start (05 §5, `select_for_update`); two parallel jobs cannot exceed the limit (test).
7. Upgrade/downgrade with correct `replacementBehavior`; downgrade leaves existing live pages in place.
8. Cancelling in the app → `appSubscriptionCancel(prorate:true)` + confirmation email.
9. Webhook `app_subscriptions/update` updates the status and sends event `trial_started` on the first approval; daily reconcile task (08 §5) reports discrepancies.

## Assumptions made during build
- **Beat-task queues (00-decisions):** beat tasks not assigned to a specific queue in 05 default to the `low` queue (BUILD_LOG item 10).
- **Prices:** Pro USD 59.00 and Agency USD 149.00 per 30 days (annual 590/1490) — confirmed by Paul 2026-10-01; `plans.py` aligned in commit `e26bb0d` (BUILD_LOG A1).
