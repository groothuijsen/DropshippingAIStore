# F09 — Bundles (volume, BOGO, free gift)

**References:** 04 §1 (`mq-bundle-picker`) and §2 (Discount Function), 07 §2–3, 02 (`Offer`), 03 §5 (`discount_create`, `metaobject_upsert`).

## Acceptance criteria

1. The merchant creates a volume offer with 2–4 tiers (min. quantity ascending, percentage 1–70, ascending); invalid combinations are rejected.
2. **When** activated, **then** there exists one automatic app discount (`discountClasses: [PRODUCT]`) with an `offer_config` metafield that validates against `OfferConfig`, an `$app:offer_display` metaobject with only quantities/percentages (no prices), and a product metafield `offer`. Activation is refused at 20 active Mosaiq discounts or 25 active automatic discounts in the whole shop (including other apps).
3. In the storefront, `mq-bundle-picker` calculates in Liquid with the current `variant.price` per tier: total price, savings vs. the **current** single-unit price × quantity, and unit price if mandatory. Never compare-at × quantity. After a price change by a sync app the amounts are correct without Mosaiq having to do anything.
4. In the checkout the discount matches the widget for all Function test cases (04 §2 Tests), tested in the dev store.
5. **Given** `ends_at` empty, **then** `show_timer` cannot be switched on (UI, model, DB). **Given** `ends_at` has passed, **then** no timer, discount inactive (Shopify `endsAt`), `Offer.status = ended` via beat task.
6. Free gift: the widget adds the gift variant with `_mq_gift` as soon as the condition is met and removes it when the condition no longer holds; the Function gives 100% only if condition + attribute are met.
7. Deactivating deletes the discount, metaobject and metafield (idempotent).
8. Works on products from sync apps without changing a single locked field (test with DSers and Printify fixture).

## Assumptions made during build
- **Discount limits (Q13):** Shopify allows 25 active automatic discounts per shop including those of other apps; the editor warns near the limit.
- **Function API:** target `cart.lines.discounts.generate.run` with `functionHandle` (`functionId` is deprecated in API 2026-07).
