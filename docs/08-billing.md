# 08 — Billing and limits

All payments via the Shopify Billing API. No usage charges, no revenue caps, no automatic add-on purchases.

## 1. Plans and limits (per 30-day period)

| Limit | `starter` | `pro` | `agency` |
| --- | --- | --- | --- |
| Store generations (`kind=store`, published) | 3 | 15 | 50 |
| Live pages at the same time (counted live, not per period) | 15 | 60 | unlimited |
| AI images | 30 | 150 | 500 |
| Active offers (Offers) | 20 | 20 | 20 (technical limit, see 02 `Offer`) |
| Bundle/cart revenue | unlimited | unlimited | unlimited |
| A/B test, analytics (v1.1) | — | yes | yes |
| Shared templates across shops (v1.2) | — | — | yes |

Limits are stored as data in `apps/billing/plans.py` (`PLAN_LIMITS`), not scattered through the code. Checks via `billing.limits.reserve(shop, "store_generations"|"ai_images", amount)` (reserves, see 05 §5) and `billing.limits.check_pages_live(shop)` (counts `Page` with status `live`) → `LimitResult(allowed, remaining)`.

- Page generation (`kind=page`) does not count as a store generation; it only counts towards "live pages" once live.
- Reserve at job start, convert to consumption on success, release on failure (05 §5).
- Downgrade with more live pages than the new limit: existing pages stay live; new publications are blocked until below the limit.

## 2. Creating a subscription

Mutation `subscription_create`:

```graphql
mutation SubscriptionCreate($name: String!, $returnUrl: URL!, $trialDays: Int, $test: Boolean,
                            $lineItems: [AppSubscriptionLineItemInput!]!,
                            $replacementBehavior: AppSubscriptionReplacementBehavior) {
  appSubscriptionCreate(name: $name, returnUrl: $returnUrl, trialDays: $trialDays, test: $test,
                        lineItems: $lineItems, replacementBehavior: $replacementBehavior) {
    confirmationUrl
    appSubscription { id status trialDays currentPeriodEnd }
    userErrors { field message }
  }
}
```

- `lineItems`: `[{ plan: { appRecurringPricingDetails: { price: { amount: 29.00, currencyCode: USD }, interval: EVERY_30_DAYS } } }]`; annual: `interval: ANNUAL` with the annual price from 00-decisions.
- `name`: `Mosaiq Starter`, `Mosaiq Pro`, `Mosaiq Agency` (+ ` (annual)`).
- `returnUrl`: `https://admin.shopify.com/store/{store_handle}/apps/mosaiq/billing/return` — this way the merchant lands back in the embedded app. `store_handle` = shop domain without `.myshopify.com`. Verify during T-060.
- `test`: `SHOPIFY_BILLING_TEST`.
- `trialDays`: 7, or 0 if the domain already had a trial (§4).
- `replacementBehavior`: upgrade → `APPLY_IMMEDIATELY`; downgrade → `APPLY_ON_NEXT_BILLING_CYCLE`.
- Redirect to `confirmationUrl` via App Bridge (`open(url, "_top")`).

## 3. Tracking status

- Source of truth: webhook `app_subscriptions/update` + on every admin load (max. 1× per 10 min per shop, cached) `current_installation.activeSubscriptions`.
- Access to generation/publishing only with status `active` (including trial). Other statuses → plan screen.
- `frozen` (merchant does not pay Shopify): everything read-only, the storefront keeps working (Shopify freezes it itself).

## 4. Trial and abuse

- New model `TrialLedger(domain_sha256 CharField(64) unique, first_trial_at DateTimeField)` — **is not deleted on `shop/redact`** (contains only a hash of the shop domain, no personal data). Include this in the privacy policy.
- If the hash already had a trial → `trialDays = 0`.
- 48 hours before the trial ends: email + banner "Je proefperiode eindigt op {datum}. Wil je niet doorgaan? Zeg hier met één klik op." ("Your trial ends on {date}. Don't want to continue? Cancel here with one click."). Beat task every hour.

## 5. Cancellation

- In-app button "Abonnement opzeggen" ("Cancel subscription") → confirmation dialog → `appSubscriptionCancel(id, prorate: true)`.
- Confirmation email: "Je abonnement is opgezegd. Je wordt niet meer gefactureerd." ("Your subscription has been cancelled. You will no longer be billed.")
- Uninstall: Shopify cancels the subscription itself (verified in the docs); Mosaiq sends the confirmation email after `app/uninstalled`.
- Daily beat task `billing.tasks.reconcile` (active shops only, token valid): compares `Subscription.status` with `currentAppInstallation.activeSubscriptions`; difference → update + alert. After uninstall, checking via the API is not possible; Shopify cancels itself. Complaints about charges after uninstall are handled via SOP-3 (refund).
- Refund policy: charge within 7 days after cancellation → full refund via the Partner Dashboard, handled within 24 hours (SOP-3).

## 6. Tests

- Create a subscription (test mode) in the dev store, approve it, receive the webhook, status `active`.
- Upgrade and downgrade with the correct `replacementBehavior`.
- Second installation on the same domain → `trialDays = 0`.
- Limit reached → `PLAN_LIMIT_REACHED`, counter not exceeded with concurrent jobs (test with two parallel transactions, `select_for_update`).

## v1.1 additions

See `docs/12-v1.1-store-builder.md` §7 (limits for store builds and page edits). That document takes precedence for F15–F18.
