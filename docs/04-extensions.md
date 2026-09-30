# 04 — Extensions: Theme App Extension and Discount Function

Generate both with the Shopify CLI; do not write them from scratch:

```
npx shopify app generate extension --template theme_app_extension --name theme-blocks
npx shopify app generate extension --template discount --flavor vanilla-js --name bundle-discount
```

After generation, check which Function target the template uses and run `npx shopify app function schema` + `typegen`. The input query below is a design; the generated schema is authoritative.

## 1. Theme App Extension (`extensions/theme-blocks/`)

### General rules
- No jQuery, no external CDNs, no inline `<script>` larger than 2 KB.
- JS per block ≤ 30 KB (minified), loaded via `"javascript": "mq-<blok>.js"` in the schema, `defer`.
- All colors/fonts via CSS variables from the `mq-tokens` embed (`var(--mq-primary)` etc.), with fallback to the theme color.
- All text via `locales/en.default.json`, `nl.json`, `de.json`. No hardcoded text in Liquid.
- Metafields always as `<object>.metafields["$app:mosaiq"].<key>.value` (03 §5.3). Metaobjects are only visible if they are `ACTIVE`.
- Accessible: WCAG 2.1 AA, keyboard-operable, `aria-live` on price updates.

### Blocks (target `section`, added via deep link)

| Handle | Template(s) | Renders | Data source | Settings (schema) |
| --- | --- | --- | --- | --- |
| `mq-page-sections` | product, page, index | All sections from the `$app:page_content` entry for the current language (03 §5.1); images per `image_slot` from the fields `image_<slot>`; AI label as `ai_image_disclosure` | product: `product.metafields["$app:mosaiq"].page.value`; page: `page.metafields["$app:mosaiq"].page.value`; index: `shop.metafields["$app:mosaiq"].home_page.value` | `show_ai_label` (checkbox, on by default), `max_width` (range 800–1400) |
| `mq-bundle-picker` | product | Tiers as radio options with total price, savings, unit price per tier; optional timer | `product.metafields["$app:mosaiq"].offer.value` → `$app:offer_display`, `variant.metafields["$app:mosaiq"].unit_price.value` | `layout` (select: stacked/grid), `highlight_tier` (number) |
| `mq-gpsr` | product | Manufacturer, EU responsible person, product identification, warnings in the store language | `product.metafields["$app:mosaiq"].gpsr.value` | `collapsed` (checkbox) |
| `mq-price` | product | Price + unit price + (only if present) Omnibus prior price and correct percentage; stock notice and delivery-time notice per 07 §3 | `variant.price`, `variant.metafields["$app:mosaiq"].prior_price.value`, `unit_price`, `variant.inventory_management`, `variant.inventory_quantity`, `shop.metafields["$app:mosaiq"].settings.value` | `show_stock` (checkbox), `show_cutoff` (checkbox) |

### App embeds (target `head` or `body`, enabled via deep link)

| Handle | Target | Does |
| --- | --- | --- |
| `mq-tokens` | `head` | Sets `:root { --mq-primary: …; --mq-radius: …; --mq-font-heading: …; }` from `shop.metafields["$app:mosaiq"].design_tokens.value`. **Fonts:** no `font_picker` (does not work reliably in app extensions: fonts do not load in the theme editor) and no Google Fonts CDN (legally risky in Germany due to transfer of IP addresses). Instead, 6 open-license fonts (OFL) as `woff2`, Latin subset only, 2 weights, in the extension's `assets/fonts/` (≤ 600 KB combined): Inter, Manrope, DM Serif Display, Playfair Display, Nunito, Space Grotesk. `@font-face` with `{{ 'fonts/<name>-<gewicht>.woff2' \| asset_url }}` and `font-display: swap`. Font `null` in the tokens → no `@font-face`, blocks inherit the theme font. No JS. |
| `mq-cart-drawer` | `body` | Own cart drawer: intercepts add-to-cart forms, uses the Ajax Cart API (`/cart.js`, `/cart/add.js`, `/cart/change.js`), shows upsells, reward bar, free gift. Has an `enabled` setting so the merchant can revert to the theme drawer. |
| `mq-withdrawal-link` | `body` | Places the withdrawal link (label per store language from `shop.metafields["$app:mosaiq"].withdrawal.value`, 07 §8) in the first `<footer>` element; if that does not exist, as a fixed small link at the bottom left. The link goes to the app proxy `/apps/mosaiq/withdraw` (guest form, no login). Always visible, on every page. |

### Timer rules in `mq-bundle-picker` (hard, see 07 §3)
- Render the timer **only** if `offer_display.ends_at` is set and lies in the future (compare with `'now' | date: '%s'`).
- Count down in JS to exactly `ends_at` (ISO string in `data-ends-at`). At 0: hide the timer, restart nothing, do not reload the page.
- No `localStorage`/cookies to store a per-visitor start time.

### Price display in `mq-bundle-picker` (hard, see 07 §1–2)
- **Everything is calculated in Liquid using the current `variant.price` (in cents)**; the metaobject contains only quantities and percentages. The Python functions in `compliance/` are the reference implementation for the admin preview and for tests; a test compares the Liquid result (not possible via Shopify CLI theme check → manual spot check in T-072 with 5 prices) with Python.
- Unit price conversion factors in the snippet `mq-unit-factor.liquid` (same table as 07 §2.2).
- Tier total = `variant.price × aantal × (1 − korting)` (price × quantity × (1 − discount)), rounded per the Shopify money filter.
- "Regular price" for the tier = `variant.price × aantal` (price × quantity; the **current** unit price), never `compare_at_price × aantal`.
- Savings = regular price − tier total. Show as an amount; show a percentage only if it is a whole number rounded down.
- Unit price per tier = tier total ÷ (quantity × net content converted to the reference unit), see 07 §2.
- Show the variant's struck-through `compare_at_price` only via `mq-price` and only if `prior_price` exists.

### Add to cart
- Bundle: `POST /cart/add.js` with `{ items: [{ id, quantity, properties: { "_mq_offer": "<offer-uuid>" } }] }`. The discount comes from the Function, not from the widget.
- Free gift: the widget adds the gift variant with property `_mq_gift: "<offer-uuid>"` as soon as the condition is met, and removes it when the condition no longer holds.

## 2. Discount Function (`extensions/bundle-discount/`)

### Purpose
Applies discounts for `Offer` types `volume`, `bogo` and `free_gift`. One automatic discount per active `Offer` (`discountAutomaticAppCreate`), with the configuration as a metafield on the discount.

### Configuration (metafield on the discount, `namespace: "$app:mosaiq"`, `key: "offer_config"`, type `json`)

```json
{
  "offer_id": "uuid",
  "kind": "volume | bogo | free_gift",
  "product_ids": ["gid://shopify/Product/1"],
  "tiers": [
    {"min_qty": 2, "type": "percentage", "value": "10.0"},
    {"min_qty": 3, "type": "percentage", "value": "15.0"}
  ],
  "bogo": {"buy_qty": 1, "get_qty": 1, "get_percentage": "100.0"},
  "free_gift": {"gift_variant_id": "gid://shopify/ProductVariant/9", "min_qty": 2, "min_subtotal": null},
  "labels": {"nl": "Bundelkorting", "en": "Bundle discount", "de": "Bundelrabatt"}
}
```

Only the block matching `kind` is filled; the others are `null`.

Pydantic model `offers.schemas.OfferConfig` validates this before writing. `value` and percentages as strings with one decimal.

### Logic (pseudo, deterministic, no network)

```
config = parse(discount.metafield)
eligible = cart.lines where merchandise.product.id in config.product_ids

volume:
  qty = sum(line.quantity for eligible)
  tier = highest tier with min_qty <= qty; no tier -> no operations
  candidate per eligible line: percentage tier.value

bogo:
  units = eligible lines expanded into single units, sorted by price ascending
  group = buy_qty + get_qty; free_units = floor(len(units)/group) * get_qty
  discount on the cheapest free_units units: percentage get_percentage,
  as a candidate per cartLine with `quantity` = number of discounted units of that line

free_gift:
  condition = qty(eligible excluding the gift line) >= min_qty  (or subtotal >= min_subtotal)
  gift_line = line with merchandise.id == gift_variant_id and attribute _mq_gift == offer_id
  condition true and gift_line exists -> 100% on 1 unit of gift_line
```
- Function target: **`cart.lines.discounts.generate.run`** (unified Discount Function API; result type `CartLinesDiscountsGenerateRunResult`). Generate the input query and types with the CLI; do not write them from memory.
- Output per offer: **one** candidate with all target lines, so that `selectionStrategy: FIRST` suffices:
  ```js
  return { operations: [{ productDiscountsAdd: {
    candidates: [{
      message: label,                                   // labels[primary language], max. 50 characters
      targets: lines.map(l => ({ cartLine: { id: l.id, quantity: l.qty } })),  // quantity only for bogo/gift
      value: { percentage: { value: pct } }
    }],
    selectionStrategy: "FIRST"
  }}]};
  ```
  No condition met → `{ operations: [] }`.
- Reading the configuration in the input query: `discount { discountClasses metafield(namespace: "$app:mosaiq", key: "offer_config") { value } }`. Write with **exactly the same** namespace string (`$app:mosaiq`) via the `metafields` field of `discountAutomaticAppCreate`. Differing strings (e.g. `$app` versus `$app:mosaiq`) yield an empty config: test this first in T-070.
- Creation: `discountAutomaticAppCreate(automaticAppDiscount: { title, functionHandle: "bundle-discount", discountClasses: [PRODUCT], startsAt, endsAt, combinesWith: {…}, metafields: [{ namespace: "$app:mosaiq", key: "offer_config", type: "json", value }] })`. `functionHandle` exists since 2025-10; `functionId` is deprecated in 2026-07. Never send both (results in a user error).
- `combinesWith`: `productDiscounts: false`, `orderDiscounts: true`, `shippingDiscounts: true`.
- Limit: 25 active automatic discounts per shop, including other apps (02 `Offer`).

### Tests
- Unit tests per kind with `npx shopify app function run --input fixtures/<case>.json`, compared against expected output. Minimum: no tier reached, lowest tier, highest tier, mixed products, BOGO with an odd quantity, gift without condition, gift with condition, gift attribute from another offer.

## 3. `OfferRules` per kind (`offers.schemas`)

```python
class Tier(BaseModel):
    min_qty: int = Field(ge=2, le=20)
    percentage: Decimal = Field(gt=0, le=70, decimal_places=1)

class VolumeRules(BaseModel):
    tiers: list[Tier] = Field(min_length=1, max_length=4)   # min_qty and percentage strictly ascending (validator)

class BogoRules(BaseModel):
    buy_qty: int = Field(ge=1, le=5)
    get_qty: int = Field(ge=1, le=5)
    get_percentage: Decimal = Field(gt=0, le=100, decimal_places=1)

class FreeGiftRules(BaseModel):
    gift_variant_gid: str
    min_qty: int | None = Field(default=None, ge=1)
    min_subtotal: Decimal | None = Field(default=None, gt=0)   # exactly one of min_qty/min_subtotal

class CartUpsellRules(BaseModel):
    upsell_product_gids: list[str] = Field(min_length=1, max_length=3)

class RewardBarRules(BaseModel):
    thresholds: list[dict] = Field(min_length=1, max_length=3)   # {"amount": Decimal, "label": {language: str}}
    shipping_rule_confirmed: bool                               # merchant confirms that the shipping rule exists in Shopify

OfferRules = VolumeRules | BogoRules | FreeGiftRules | CartUpsellRules | RewardBarRules  # selected by Offer.kind
```

- `volume`/`bogo`/`free_gift` → Discount Function + `$app:offer_display`.
- `cart_upsell`/`reward_bar` → no discount; merged into the app-data metafield `cart` (03 §5.2). `upsell_handles` = handles of the selected products; the embed reads them with `all_products[handle]` (max. 3).
