# F17 — EU price advisor

**References:** 12 §1 (D-17.1), §2.6, §4 (`product_variants_bulk_update`, `inventory_item_cost`), §6, §8; 06 §3 (ownership guard), 07 §1 (Omnibus).

Calculates a consumer price including VAT from cost, shipping, payment fees, returns allowance and target margin, per market. Writes the price only where Mosaiq may write it.

## Formula (`compliance.pricing_advisor.advise`)

Inputs per variant and market: supplier cost `C`, shipping cost per unit `S`, ad cost per order `A` (optional, default 0), payment fee fixed `F`, payment fee percentage `p` (on the gross price), returns allowance `r` (share of net revenue), target margin `m` (share of net revenue), VAT rate `v` of the market.

```text
net price          N = (C + S + A + F) / (1 − r − m − p × (1 + v))
consumer price     P = N × (1 + v)
break-even price   P0 = same formula with m = 0
rounded price      Pr = smallest price ≥ P ending in the shop's price_ending (.95, .99 or .00)
actual margin      m_actual = (Pr/(1+v) − C − S − A − F − p×Pr − r×Pr/(1+v)) / (Pr/(1+v))
```

All money as `Decimal`, rounded half-up to 2 decimals only at the end. If the denominator `1 − r − m − p × (1 + v)` is below `0.05`, return the error "Target margin too high for these costs" and no price.

VAT standard rates (data in `compliance/vat_rates.py`, with source and date per row): NL 21%, BE 21%, DE 19%, AT 20%, FR 20%, LU 17%, IE 23%. GB is outside the EU: show "VAT rules for GB not covered". Reduced rates are not handled; the screen says so.

## Acceptance criteria

1. **Test cases** (must pass exactly, `price_ending = 95`):
   - C=8.00, S=4.00, A=0, F=0.30, p=0.029, r=0.05, m=0.30, v=0.21 → N=20.00, P=24.20, Pr=24.95.
   - same, m=0 → P0=16.27.
   - same, v=0.19 → P=23.78, Pr=23.95.
   - same, A=5.00 → P=34.04, Pr=34.95.
   - r+m+p(1+v) ≥ 0.95 → error, no price.
2. **Defaults.** Cost defaults to the variant's `inventoryItem.unitCost` when set (converted to the shop currency only if equal; otherwise ask), else empty. Fees, returns allowance, margin, price ending and markets come from `PricingSettings` (editable at `/app/settings/store/`).
3. **Display.** Per market: break-even price, advised price, rounded price, actual margin at the rounded price, and a cost breakdown. Current price shown next to it with the difference.
4. **Apply — writable products.** **Given** `assert_writable(product, "price")` passes, **when** the merchant clicks "Apply" for one market (the shop's base currency market), **then** Mosaiq writes the price with `productVariantsBulkUpdate` (price only), stores `PriceAdvice.applied_at`, and logs it in `AuditLog`.
5. **Apply — sync-app products.** **Given** the product is managed by a sync app (06 §3), **then** there is no Apply button; the screen shows "Set this price in <app name> (price rules)" and the advised price to copy. Test: the guard raises and no HTTP call is made.
6. **Omnibus warning.** **When** the advised price is higher than the current price, **then** the warning from 12 §8 is shown.
7. **Markets.** Prices per market other than the base currency are advice only (Shopify Markets price lists are out of scope); the screen says so.

## Assumptions made during build
_(filled by Hermes, T-130, 2026-10-02)_

1. **Rounding**: "smallest price ≥ P ending in price_ending" computed on integer cents with ceiling, then adjusted to the ending suffix (.95/.99/.00); half-up to 2 decimals applied only to displayed money values.
2. **Boundary**: error when denominator `1 − r − m − p×(1+v) <= 0.05` (spec test case "≥ 0.95 → error" interpreted inclusively at the boundary).
3. **Defaults on screen**: cost/shipping/ad_cost are free-form inputs (defaults from `inventoryItem.unitCost` need the `inventory_item_cost` GraphQL query — wired in T-131 with Apply).
4. **Markets note**: non-base-currency markets show advice only + the explicit "Shopify Markets price lists are out of scope" note (F17-7).
5. **GB**: `vat_rate_for("GB")` returns None → screen shows "VAT rules for GB not covered"; no price computed.
