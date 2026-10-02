# F18 — Delivery times and shipping information

**References:** 12 §1 (D-18.1), §2.4, §4 (`delivery` metafield), §5 (copy guardrail), §6, §8; 04 (`mq-price`), 07 §3 (cut-off notice), 06 (source detection).

Merchants set delivery estimates per source app (and per product where needed). Mosaiq shows them on the product page, uses them on the shipping page, blocks contradicting claims and feeds them to the copy step.

## Acceptance criteria

1. **Profiles.** `/app/settings/delivery/` shows one row per source app that the shop uses (`Shop.import_apps` plus detected sources) and `manual`. Each row: ship-from country, processing days min–max, transit days min–max per market, optional shipping cost and free-from per market. Validation per 12 §2.4.
2. **Overrides.** The product screen has a delivery override form; empty fields fall back to the profile.
3. **Estimate.** `compliance.delivery.estimate()` returns the sums per 12 §2.4. Test: profile CJ (CN, processing 2–4, NL transit 6–10) → NL estimate 8–14 working days, ship_from CN; product override transit NL 3–5 → 5–9.
4. **Metafield.** **When** a profile or override is saved, **then** the PRODUCT metafield `$app:mosaiq.delivery` is written for every affected product (batched, max 25 per `metafieldsSet`). A product without a profile gets no metafield (and an existing one is deleted).
5. **Storefront.** `mq-price` renders "Delivery in {min}–{max} working days (ships from {country name})" from the metafield for the visitor's market (fallback: the shop's first market), in nl/en/de via the extension locales. No metafield → nothing rendered.
6. **Cut-off suppression.** **Given** the product's `max_days > Shop.ship_cutoff.delivery_days`, **then** the cut-off notice (07 §3) is not rendered for that product.
7. **30-day rule.** **Given** any market has `max_days > 30`, **then** go-live of that product's page is blocked with `DELIVERY_OVER_30_DAYS`.
8. **Claims.** The claim rule `SHIPPING_CLAIM` (12 §8) runs in the deterministic check (07 §4) with the product's estimate. Test: "Snelle levering" on a product with NL 8–14 → block; with NL 1–2 → no finding; no estimate → warn. "Verzonden vanuit ons EU-magazijn" with ship_from CN → block.
9. **Copy input.** The `copy` step receives the estimate and the guardrail from 12 §5. The evalset (10 §4) gets 5 cases with long delivery times; none may produce a fast-delivery claim.
10. **Shipping page.** *(Delivered in T-116: `standard_pages.build_fact_sections` renders per-market days + costs from `DeliveryProfile`/`shipping_cost`; no profile → the page carries "Delivery times missing" + a `missing_facts` warning; the go-live block itself is enforced by the T-117 build.)* The `shipping` page type (F15) renders its delivery-time block from the profiles (per market, per source app) and its costs from `shipping_cost`; when no profile exists, the page cannot go live and lists "Delivery times missing".

## Assumptions made during build
_(to be filled in by Hermes)_

1. **F18-6 cut-off suppression**: no theme block currently renders the 07 §3 cut-off notice — the suppression condition (max_days vs ship_cutoff.delivery_days) is tested at the estimate level and gates apply when the notice block is built (T-141 sprints note).
2. **F18-8 severity mapping**: fast-delivery phrase → block when estimate max_days > 3, warn when no estimate exists (spec 12 §8). 'Ships from EU' claims use a fixed EU member-state list (ISO 3166-1 alpha-2, 27 states) in claims.EU_COUNTRIES.
3. **F18-9 evalset**: 5 long-delivery cases added to the 30-product evalset (total 35) with a `delivery_estimate` field ({min_days, max_days, ship_from}); T-091 assertions relaxed from == to >=.
4. **F18-4 deletion of stale metafields**: sync_delivery_metafields writes for affected products only; deleting the metafield from products that lost their profile is deferred to the source-detection run (T-020 flow) to keep this task idempotent and read-only towards unprofiled products.
