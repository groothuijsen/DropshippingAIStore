# 06 — Dropship and POD integrations

## 1. Strategy

Mosaiq builds **no** own integration with suppliers and does **no** fulfillment. Merchants import products with their existing app (DSers, CJdropshipping, Zendrop, AutoDS, Printify or others). That app creates a regular Shopify product and synchronizes price, inventory and variants. Mosaiq builds the store, pages and offers **around** that product.

Reason: own integrations are expensive to maintain, and two apps writing the same fields cause silent errors (one overwrites the other).

## 2. Main rule (hard)

> On a product that Mosaiq **did not create itself**, Mosaiq writes exclusively:
> 1. `templateSuffix` (only `"mosaiq"`, and only if `Shop.mosaiq_templates_ready`), and
> 2. metafields in namespace `$app:mosaiq`.
>
> All other fields are "locked".

This also applies if the source appears to be `manual` but the product was not created by Mosaiq. Only products with `ProductSource.source = manual` **and** created via `product_create_manual` are fully editable.

## 3. Ownership matrix

| Field | Mosaiq product | Product from sync app or unknown |
| --- | --- | --- |
| `title` | write | **never** |
| `descriptionHtml` | write | **never** (MVP). v1.1: opt-in per product with a warning |
| `price`, `compareAtPrice` | write (merchant confirms) | **never** |
| variants, options, SKU, barcode | write | **never** |
| inventory | **never** (Shopify/merchant) | **never** |
| product media (gallery) | write | **never**; AI images only in Files + metaobject |
| `tags`, `vendor`, `productType` | write | **never** |
| SEO title/description | write | **never** (MVP); show as a suggestion to copy |
| `templateSuffix` | write | write |
| `$app:mosaiq` metafields | write | write |

The client layer enforces this: `sources.guards.assert_writable(shop, product_gid, fields: set[str])` raises `LockedFieldError` before every product mutation. There is a test that calls every product mutation function on a locked product and expects the error.

## 4. Source detection (only for display and GPSR assistance)

Because everything except Mosaiq products is locked anyway, detection is **not** safety-critical. It serves to:
- show in the UI "Beheerd door DSers" ("Managed by DSers") (explains why fields are not editable);
- suggest GPSR fields (e.g. supplier as a starting point);
- understand support questions.

### 4.1 Strongest signal: fulfillment location
Virtually all sync apps create their own fulfillment location or fulfillment service on which their variants are stocked. Since API 2024-07, `ProductVariant.fulfillmentService` no longer exists; the service follows from where the item is stocked. Read this with operation `variant_locations` (03 §5; scope `read_inventory`):
`inventoryItem.inventoryLevels.nodes[].location { name isFulfillmentService fulfillmentService { handle serviceName } }`.

### 4.2 Onboarding question
"Met welke apps importeer je producten?" ("Which apps do you use to import products?") Multiple choice: DSers, CJdropshipping, Zendrop, AutoDS, Printify, Printful, Andere (Other), Geen (None). Store in `Shop.import_apps` (02). Used as a safety net when a product is stocked at the regular store location (DSers and AutoDS allow this).

### 4.3 Rules (data in `apps/sources/rules.py`, strongest first)

```python
# (source, signal, pattern, verified?)  — sources: the apps' help centers, Sept. 2026
SOURCE_RULES = [
    ("dsers",    "fulfillment_handle",  r"^dsers-fulfillment-service$",          True),   # help.dsers.com
    ("printify", "fulfillment_handle",  r"^printify$",                           False),  # location name "Printify" is confirmed, handle inferred
    ("printify", "location_name",       r"(?i)^printify$",                       True),
    ("printful", "location_name",       r"(?i)^printful$",                       True),   # help.printful.com
    ("autods",   "location_name",       r"(?i)^autods",                          True),   # help.autods.com
    ("zendrop",  "location_name",       r"(?i)^zendrop",                         True),   # support.zendrop.com
    ("cj",       "location_name",       r"(?i)cj ?dropshipping|^cj\b",          False),  # "own CJ location" confirmed, exact name not
    ("printify", "vendor",              r"(?i)^printify$",                       True),   # default vendor, merchant can change it
    ("cj",       "sku",                 r"^CJ[A-Z0-9]{4,}",                      False),  # weak, not confirmed
]
```

Do not use as a signal:
- **Vendor for DSers and Printful**: they set the merchant's store name as the vendor.
- **Tags**: none of the apps adds tags by default.
- **Metafields**: apps write to their own `$app:` namespace, which other apps cannot read.
- **High inventory** (Zendrop 30.000/50.000, Printful 9.999): only as an extra hint in the UI, never as a rule.

Decision order: the first match on a rule with `fulfillment_*`/`location_name` wins → `detected_by = fulfillment_location`. Otherwise a vendor/sku rule → `vendor`/`sku`. Otherwise: if the merchant uses exactly one import app → that app (`onboarding`). Otherwise `unknown_app`. Everything except `created_by_mosaiq` stays locked (§2), regardless of the outcome.

### 4.4 Verification (T-020)
Rules with `False` must be confirmed: install the app in the dev store, import one product, run `variant_locations` via `scripts/gql.py`, save as `tests/fixtures/shopify/variant_locations_<app>.json` and put the real handle/name in the rule. Also record whether DSers and AutoDS put products on the store location by default. If an app cannot be tested (no trial): keep the rule as `False`; the onboarding question covers it.

## 5. Consequences for other modules

| Module | Consequence |
| --- | --- |
| Omnibus (07 §1) | Sync apps change prices frequently. Every change comes in via `products/update` → `PriceHistory`. The lowest 30-day price is therefore automatically correct, even if the app raises the price just before a promotion. |
| Stock notices (07 §3) | Only show if the variant tracks inventory (`inventory_management` = shopify) and the app synchronizes inventory. Otherwise never show a stock notice. |
| Bundles (04 §2) | The discount lives in the Function; the sync app sees regular orders with a discount and fulfills normally. Test with one DSers product and one Printify product that the order arrives at the app. |
| GPSR (07 §5) | Dropshipping from outside the EU → virtually always `manufacturer_in_eu = False` → EU responsible person mandatory. Show an explanation in the UI. Publishing stays blocked until complete. |
| Images (05 §4.4) | Reference images = the product media that the app imported. The merchant confirms they are allowed to use them (checkbox at first generation, stored in `AuditLog`). |
| Import via URL (05 §4.1) | AliExpress/Amazon often block this. Advise in the UI: "Importeer eerst via je dropship-app, kies daarna het product in Mosaiq." ("Import via your dropship app first, then select the product in Mosaiq.") |

## 6. Out of scope

- Own supplier catalog or product research.
- Forwarding orders to suppliers.
- Calculating pricing rules or margins.
- Calling the Printify API directly (v2 may do this for mockups; not in MVP).
