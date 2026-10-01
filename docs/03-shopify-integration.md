# 03 — Shopify integration

API version: `SHOPIFY_API_VERSION` (`2026-07`). All operations via GraphQL. Run every operation below against the dev store with `scripts/gql.py` first and save the response as a fixture (AGENTS.md §5).

## 1. `shopify.app.toml` (initial version)

```toml
client_id = "<SHOPIFY_API_KEY>"
name = "Mosaiq"
handle = "mosaiq"
application_url = "https://app.mosaiq.<domain>/app/"
embedded = true

[access_scopes]
# Minimal. No write_themes. New scope = update of this document + listing.
# - No metaobject scopes: since 2026-04 an app needs no scope for its own `$app:` metaobject types
#   (shopify.dev/changelog/metaobject-scopes-not-required-for-app-metaobjects).
# - pageCreate: write_online_store_pages (or write_content). fileCreate: write_files. shopLocales: read_locales.
# - read_inventory: needed to read the fulfillment location per variant for source detection (06 §4).
scopes = "write_products,write_discounts,write_online_store_pages,write_files,read_inventory,read_locales,read_markets,write_online_store_navigation,write_publications"
use_legacy_install_flow = false

[auth]
redirect_urls = ["https://app.mosaiq.<domain>/auth/callback"]

[webhooks]
api_version = "2026-07"

  [[webhooks.subscriptions]]
  topics = ["app/uninstalled", "app_subscriptions/update", "products/update", "products/delete", "shop/update"]
  uri = "https://app.mosaiq.<domain>/webhooks/shopify/"   # always an absolute URL

  [[webhooks.subscriptions]]
  compliance_topics = ["customers/data_request", "customers/redact", "shop/redact"]
  uri = "https://app.mosaiq.<domain>/webhooks/shopify/compliance/"

[app_proxy]
url = "https://app.mosaiq.<domain>/proxy/"
subpath = "mosaiq"
prefix = "apps"
# Storefront URL: https://<store>/apps/mosaiq/withdraw → withdrawal form (07 §8).
# Validate every proxy request on the `signature` query parameter (HMAC-SHA256 of the sorted query, without `signature`, with SHOPIFY_API_SECRET).

[build]
include_config_on_deploy = true
```

- Verify the scope name for pages (`write_online_store_pages`) in T-005: if `pageCreate` returns "access denied", take the scope from the error message and update this document.
- `redirect_urls` is required but is not used for the installation itself under managed installation.
- There are **two apps** in the Partner Dashboard: `mosaiq-dev` (dev store + staging) and `mosaiq` (production), each with its own `shopify.app.<env>.toml` (`shopify app config link`). Client ID and secret differ per app.
- `uri` may also be a relative path (`/webhooks/shopify/`); we use absolute URLs so that staging and production do not accidentally switch over the same one.

## 2. Authentication

### 2.1 Document loads (full pages)
Shopify opens `application_url` in an iframe with query parameters `shop`, `host`, `embedded=1`, `locale` and `id_token`. Every full page navigation within the app (links, billing return, reload) is also a GET without an `Authorization` header.

Rule for `SessionTokenMiddleware`:
- **GET document load** (no `HX-Request` header): accept `id_token` from the query. Missing or expired → render `app/bounce.html`: loads App Bridge, fetches `await shopify.idToken()` and reloads the same URL with `?id_token=<token>` (plus the existing query). Never a 401 on document loads.
- **HTMX and fetch requests**: `Authorization: Bearer` only. Invalid → 401 (§2.2).
- `locale` from the query determines the UI language (`nl`/`en`/`de`, otherwise `en`), stored in `Shop.ui_locale`.

On the first load:

1. Validate `id_token` as a session token (§2.2).
2. If there is no `Shop` with a valid token for `dest`: perform token exchange (§2.3), create/update `Shop`, start installation tasks (§6).
3. Render `app/index.html` with `<meta name="shopify-api-key" content="{SHOPIFY_API_KEY}">` and App Bridge as the **first** script in `<head>`.

### 2.2 Validating the session token (every admin request)
- Header: `Authorization: Bearer <jwt>` (or `id_token` on the first load).
- `jwt.decode(token, SHOPIFY_API_SECRET, algorithms=["HS256"], audience=SHOPIFY_API_KEY, leeway=10)`.
- Check: `exp`, `nbf` (via PyJWT), `dest` is `https://<shop>.myshopify.com`, `iss` starts with `dest` and ends with `/admin`.
- Shop domain = host of `dest`. Set `request.shop` via middleware `core.middleware.SessionTokenMiddleware`.
- Invalid/expired on HTMX/fetch: HTTP 401 with header `X-Shopify-Retry-Invalid-Session-Request: 1`.
- **CSRF:** all `/app/` views are `csrf_exempt`. Reason: authentication runs via a Bearer token in a header (not via cookies), so CSRF does not apply, and third-party cookies in the Shopify iframe are blocked by browsers. Webhooks and the app proxy validate HMAC/signature.

### 2.3 Token exchange
```
POST https://{shop}/admin/oauth/access_token
Content-Type: application/json

{
  "client_id": SHOPIFY_API_KEY,
  "client_secret": SHOPIFY_API_SECRET,
  "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
  "subject_token": <session token>,
  "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
  "requested_token_type": "urn:shopify:params:oauth:token-type:offline-access-token",
  "expiring": 1
}
```

**Expiring offline tokens are mandatory** for public apps created on or after 1 April 2026 (Mosaiq falls under this). The default value of `expiring` is 0, so **always send `"expiring": 1`**. Source: [shopify.dev – offline access tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens).

- Response: `access_token`, `expires_in` (3600 s = 1 hour), `refresh_token`, `refresh_token_expires_in` (7.776.000 s = 90 days), `scope`. Encrypt both tokens with Fernet; store in `Shop.access_token_encrypted`, `Shop.refresh_token_encrypted`, `Shop.access_token_expires_at`, `Shop.refresh_token_expires_at`, `Shop.scopes`.

### 2.3a Refreshing (`core.tokens.get_access_token(shop)`)
```
POST https://{shop}/admin/oauth/access_token
{ "client_id": …, "client_secret": …, "grant_type": "refresh_token", "refresh_token": <refresh token> }
```
- Every refresh returns a **new** access token and a **new** refresh token; the old refresh token is invalid afterwards. Two workers refreshing at the same time = the second one fails and the shop has lost its token. Therefore:
  1. `get_access_token()` returns the current token if it is still valid for > 5 minutes.
  2. Otherwise: Redis lock `mq:token-refresh:<shop_id>` (timeout 30 s, `blocking_timeout` 30 s). Inside the lock, re-read the `Shop` row (another worker may have just refreshed); only then refresh and store both tokens + expiry dates in a single transaction.
  3. Refresh fails with 400/401 → `Shop.needs_reauth = True`; all tasks for that shop stop with `SHOPIFY_REAUTH_NEEDED` until the merchant opens the app (a new token exchange with the session token then follows).
- The refresh token expires after 90 days **without use**. Daily beat task `core.tasks.keep_tokens_fresh` refreshes tokens of active shops whose `refresh_token_expires_at` falls within 14 days, so that quiet stores do not lose their token.
- Never pass tokens in Celery arguments; tasks always obtain them via `get_access_token()`.

### 2.4 HTMX and session tokens (source of many bugs)
HTMX 2 uses `XMLHttpRequest`; App Bridge only adds the token automatically to `fetch`. Therefore, in `static/app/auth.js`:

`auth.js` is loaded as `<script type="module" src=".../auth.js">` and loads HTMX **itself** only after the first token has arrived, so that no `hx-trigger="load"` request goes out without a token. HTMX is therefore **not** included as a separate `<script>` in the template.

```js
// static/app/auth.js  (ES module: top-level await is allowed)
let mqToken = await shopify.idToken();
async function mqRefreshToken() { mqToken = await shopify.idToken(); }
setInterval(mqRefreshToken, 30_000);                 // tokens expire after 60 s

// 1. Register listeners FIRST, so that even the very first HTMX request gets the header.
document.body.addEventListener("htmx:configRequest", (e) => {
  e.detail.headers["Authorization"] = `Bearer ${mqToken}`;
});
document.body.addEventListener("htmx:responseError", async (e) => {
  if (e.detail.xhr.status === 401 && !e.detail.elt.dataset.mqRetried) {
    e.detail.elt.dataset.mqRetried = "1";
    await mqRefreshToken();
    window.htmx.trigger(e.detail.elt, e.detail.requestConfig.triggeringEvent?.type || "click");
  }
});

// 2. Only then load HTMX (pinned ESM build from static/vendor/).
const { default: htmx } = await import("/static/vendor/htmx.esm.js");
window.htmx = htmx;
```
Test (T-003): an element with `hx-trigger="load"` on the dashboard must send its first request with an `Authorization` header.

### 2.5 Headers
- Every admin response: `Content-Security-Policy: frame-ancestors https://{shop} https://admin.shopify.com;` (set per shop by middleware).
- No `X-Frame-Options` header on admin routes (disable Django `XFrameOptionsMiddleware` for `/app/`).

## 3. Webhooks

- Endpoints `/webhooks/shopify/` and `/webhooks/shopify/compliance/`, `csrf_exempt`, POST only.
- HMAC: compare `base64(hmac_sha256(SHOPIFY_API_SECRET, raw_body))` with `X-Shopify-Hmac-Sha256` via `hmac.compare_digest`. Invalid → 401.
- Dedupe on `X-Shopify-Webhook-Id` via `WebhookReceipt` (already exists → immediately 200).
- Return 200 within 5 s; processing in Celery task `webhooks.tasks.process_webhook(receipt_id)`.

| Topic | Action |
| --- | --- |
| `app/uninstalled` | Set `Shop.status = uninstalled` and `uninstalled_at`, running jobs → `cancelled`, wipe tokens, confirmation email "je wordt niet meer gefactureerd" (NL: "you will no longer be billed") (Shopify cancels the subscription itself). Shopify itself removes the app blocks from the theme and the app metafield definitions; Shopify retains the values for an unknown period and re-links them on reinstallation (definitions then get **new IDs**: always look them up by owner type + namespace + key, never by ID) |
| `app_subscriptions/update` | Update `Subscription.status` from the payload; on `ACTIVE` release limits |
| `products/update` | New prices per variant into `PriceHistory` if they differ from the last row; re-run source detection (06) |
| `products/delete` | Linked `Page` rows → `archived`; delete metaobject |
| `shop/update` | Update `name`, `email`, `currency_code`, `iana_timezone` |
| `customers/data_request` | Export `WithdrawalRequest` rows with the email address from the payload to the merchant (email with JSON attachment); no rows → log only |
| `customers/redact` | Delete `WithdrawalRequest` rows with the email address from the payload |
| `shop/redact` | Delete `Shop` (CASCADE). Arrives ±48 hours after uninstall. **Ignore** (log only) if the shop has since been reinstalled (`status = active` and `installed_at` > `uninstalled_at`) |

## 4. GraphQL client (`apps/core/shopify_client.py`)

- Endpoint: `https://{shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json`, header `X-Shopify-Access-Token`.
- Timeout: connect 5 s, read 30 s.
- Throttling: read `extensions.cost.throttleStatus` (`currentlyAvailable`, `restoreRate`). If `requestedQueryCost` > available, wait `(cost - available) / restoreRate` seconds. On an error with `extensions.code == "THROTTLED"`: exponential backoff 1, 2, 4, 8, 16 s, then fail with `SHOPIFY_THROTTLED`.
- Errors: top-level `errors` → `ShopifyGraphQLError`; non-empty `userErrors` in the mutation payload → `ShopifyUserError(field, message, code)`.
- HTTP 401/403 → token invalid: `Shop.status` stays, but mark `needs_reauth` in cache and show banner "open de app opnieuw" (NL: "reopen the app").

## 5. Operations (each a `.graphql` file)

| Name | Type | Purpose | Note |
| --- | --- | --- | --- |
| `shop_info` | query | `shop { id name email currencyCode ianaTimezone primaryDomain { url } billingAddress { countryCodeV2 } }` + `shopLocales { locale primary published }` | on installation and `shop/update` |
| `current_installation` | query | `currentAppInstallation { id activeSubscriptions { id name status trialDays currentPeriodEnd test } }` | ID needed for app-data metafields |
| `product_get` | query | product with `id title handle vendor tags productType descriptionHtml status options variants(first:100){ id title price compareAtPrice sku } media(first:20){ ... on MediaImage { id image { url altText } } } metafields(first:50){ namespace key value }` | source detection uses `vendor`, `tags`, `metafields` |
| `products_list` | query | paginated (`first:50`, `after`) for the product picker | only `id title featuredMedia vendor tags status` |
| `product_create_manual` | mutation | `productSet` for **manual** products; sets `ProductSource.created_by_mosaiq = True` | never on products with another source |
| `product_update_manual` | mutation | `productSet`/`productUpdate` on `created_by_mosaiq` products | guard 06 §3 |
| `metaobject_definition_ensure` | mutation | `metaobjectDefinitionCreate`; check `metaobjectDefinitionByType` first | on installation |
| `metafield_definitions_ensure` | mutation | `metafieldDefinitionCreate` for product/variant metafields (§5.2) | on installation |
| `metaobject_upsert` | mutation | `metaobjectUpsert(handle:{type, handle}, metaobject:{fields, capabilities})` | handle deterministic (02: `Page.metaobject_handles[taal]`, `Offer.metaobject_handle`) |
| `metafields_set` | mutation | `metafieldsSet` (max. 25 per call; more → split up) | owner = product, variant, page, shop or AppInstallation |
| `metafields_delete` | mutation | `metafieldsDelete(metafields:[{ownerId, namespace, key}])` | archiving, deleting `prior_price` |
| `metaobject_delete` | mutation | `metaobjectDelete(id)` | `products/delete`, deactivating an offer |
| `bulk_query` | mutation | `bulkOperationRunQuery` + poll `currentBulkOperation` (every 5 s, max. 10 min), download result JSONL | price snapshot > 250 products |
| `staged_uploads_create` | mutation | `stagedUploadsCreate(input:[{resource: IMAGE, filename, mimeType, httpMethod: POST}])` | then multipart upload to `url` with all `parameters`, file as the **last** field |
| `file_create` | mutation | `fileCreate(files:[{originalSource, contentType: IMAGE, alt}])` | then poll until `fileStatus: READY` (max. 60 s, every 2 s) |
| `page_create` | mutation | `pageCreate(page:{title, handle, body, isPublished:false, templateSuffix})` | `templateSuffix: "mosaiq"` only if `Shop.mosaiq_templates_ready` (09) |
| `page_update` | mutation | `pageUpdate` | publishing = `isPublished:true` |
| `product_template_suffix` | mutation | `productUpdate(product:{id, templateSuffix: "mosaiq"})` | the **only** product field Mosaiq may write on sourced products; only if `Shop.mosaiq_templates_ready`. If the template does not exist (anymore), Shopify falls back to the default template |
| `variant_locations` | query | `productVariants(first:100, query:"product_id:<id>"){ nodes { id sku inventoryItem { tracked inventoryLevels(first:10){ nodes { location { name isFulfillmentService fulfillmentService { handle serviceName } } } } } } }` | source detection (06 §4); scope `read_inventory` |
| `discount_create` | mutation | `discountAutomaticAppCreate` with Function (04) | `startsAt`/`endsAt` equal to `Offer` |
| `discount_update` / `discount_delete` | mutation | `discountAutomaticAppUpdate` / `discountAutomaticDelete` | |
| `subscription_create` | mutation | `appSubscriptionCreate` (08) | `test` from env |
| `subscription_cancel` | mutation | `appSubscriptionCancel(id, prorate:true)` | |

Theme detection is not done via the API (no `read_themes`); see 09, onboarding step `theme`.

### 5.1 Metaobject definitions (app-owned)

**`$app:page_content`** — one per `Page`.

| Field key | Type | Content |
| --- | --- | --- |
| `page_type` | `single_line_text_field` | `pdp`/`landing`/`advertorial`/`listicle`/`home`/`about` |
| `locale` | `single_line_text_field` | `nl`/`en`/`de` |
| `sections` | `json` | `SectionsPayload.sections` (05) for this language |
| `image_hero` | `file_reference` | slot `hero` |
| `image_lifestyle_1` | `file_reference` | slot `lifestyle_1` |
| `image_lifestyle_2` | `file_reference` | slot `lifestyle_2` |
| `image_detail_1` | `file_reference` | slot `detail_1` |
| `image_detail_2` | `file_reference` | slot `detail_2` |
| `ai_image_disclosure` | `boolean` | shows label "Afbeelding gemaakt met AI" (NL: "Image made with AI") |
| `version` | `number_integer` | = `Page.version` |

**One entry per language** (handle ends in `-<lang>`). Additional store languages are therefore not translated via `translationsRegister` but stored as their own entry; the block selects the entry whose `locale` equals `request.locale.iso_code` and falls back to the first entry.

Access: `admin: MERCHANT_READ`, `storefront: PUBLIC_READ`. Capabilities: `publishable` enabled (status `DRAFT`/`ACTIVE`).

**`$app:offer_display`** — one per active `Offer`, handle `Offer.metaobject_handle`, same access and capabilities as above. Contains **no** computed prices: the block calculates in Liquid using the current variant price (prices from sync apps change).

| Field key | Type | Content |
| --- | --- | --- |
| `kind` | `single_line_text_field` | |
| `tiers` | `json` | `[{"min_qty":2,"percentage":"10.0"}, …]` (quantities and percentages only) |
| `ends_at` | `date_time` | empty = no timer |
| `labels` | `json` | per language |

### 5.2 Metafield definitions

All with `namespace: "$app:mosaiq"`, access `admin: MERCHANT_READ`, `storefront: PUBLIC_READ`.

> **API 2026-07 (introspection-verified on the dev store 2026-10-01):**
> - `metafieldDefinitionCreate` payload field is `createdDefinition` (not `metafieldDefinition`); input type `MetafieldDefinitionInput` with `key`/`name`/`ownerType`/`type` required, `type` a plain String.
> - `metaobject_reference` and `list.metaobject_reference` definitions MUST send `validations: [{"name": "metaobject_definition", "value": "$app:<metaobject_type>"}]` — Shopify rejects them otherwise ("Validations require that you select a metaobject", `INVALID_OPTION`). `json` definitions carry no validations.
> - The metaobject definitions themselves are created via `metaobjectDefinitionCreate(definition: MetaobjectDefinitionCreateInput!)`; `fieldDefinitions[].type` is a plain String (e.g. `single_line_text_field`), not `{name: ...}`.

| Owner | Key | Type | Content |
| --- | --- | --- | --- |
| PRODUCT | `page` | `list.metaobject_reference` (to `$app:page_content`) | PDP content, one entry per language |
| PAGE | `page` | `list.metaobject_reference` | content of landing/advertorial/listicle/about |
| SHOP | `home_page` | `list.metaobject_reference` | homepage sections (block `mq-page-sections` on template `index`) |
| PRODUCT | `gpsr` | `json` | GPSR fields (07 §5) |
| PRODUCT | `offer` | `metaobject_reference` (to `$app:offer_display`) | active offer |
| PRODUCTVARIANT | `unit_price` | `json` | `{"net_quantity":"30","unit":"ml","reference":"1 l","applies":true}` |
| PRODUCTVARIANT | `prior_price` | `json` | `{"amount":"24.95","currency":"EUR","computed_at":"…","source":"history"}` — only set if there is an announced price reduction |

**Shop settings** — also owner SHOP, namespace `$app:mosaiq`, type `json`, with a definition (storefront `PUBLIC_READ`). Deliberately **no** app-data metafields on the AppInstallation: those are less well documented in Liquid (`app.metafields`) and there are reports of empty output; `shop.metafields["$app:mosaiq"]` is the documented route.

| Key | Type | Content |
| --- | --- | --- |
| `design_tokens` | `json` | `{"colors":{"primary":"#…","secondary":"#…","accent":"#…","background":"#…","text":"#…"},"fonts":{"heading":"inter|null","body":"inter|null"},"radius_px":8,"spacing_scale":1.0,"button_style":"filled|outline","heading_case":"normal|upper"}` — font `null` = inherit the theme font |
| `withdrawal` | `json` | `{"labels":{"nl":{"link":"Hier de overeenkomst ontbinden","confirm":"Ontbinding bevestigen"},"en":{…},"de":{…}},"url":"/apps/mosaiq/withdraw"}` (07 §8) |
| `settings` | `json` | `{"stock_threshold":5,"ship_cutoff":{"time":"16:00","days":["mon","tue","wed","thu","fri"],"delivery_days":1},"labels":{"nl":{…},"en":{…},"de":{…}}}` |
| `cart` | `json` | `{"enabled":true,"upsell_handles":["…"],"reward_thresholds":[{"amount":"50.00","currency":"EUR","label":{"nl":"Gratis verzending"}}]}` (F10) |

### 5.3 Namespace in Liquid (resolved)
Within a theme app extension the `$app` shorthand works, and that is the documented approach ([shopify.dev – data ownership](https://shopify.dev/docs/apps/build/custom-data/ownership)). So no environment-dependent namespace is needed.

- Metafield: `product.metafields["$app:mosaiq"].page.value` (brackets required; dot notation does not work because of `$` and `:`). Likewise `page.metafields[…]`, `shop.metafields[…]`, `variant.metafields[…]`.
- Metaobject directly: `shop.metaobjects["$app:page_content"][handle]`.
- A metaobject is only visible in Liquid with status `ACTIVE` (with `DRAFT` Liquid returns `nil`) and storefront access `PUBLIC_READ`.
- Since 1 February 2025 an extension can only read its own app metafields, not those of other apps.
- The expanded form `app--<id>--mosaiq` is only for theme code outside the extension; we do not use it.

## 6. Installation tasks (`core.tasks.on_install`, in this order)

1. `shop_info` → populate `Shop`.
2. `current_installation` → cache the installation ID.
3. Ensure metaobject and metafield definitions (idempotent).
4. Price snapshot of all active variants → `PriceHistory` with source `install_snapshot` (bulk operation if > 250 products).
5. Source detection for all products (06).
6. Write shop metafields `design_tokens`, `withdrawal`, `settings` and `cart` with default values.
7. Event `installed` (`trial_started` only comes on approval of the subscription via `app_subscriptions/update`).

## 7. Deep links to the theme editor

Source: [shopify.dev – theme app extension configuration](https://shopify.dev/docs/apps/build/online-store/theme-app-extensions/configuration). The ID is the **API key (client_id)**, not the extension UUID (that form is deprecated). `block_handle` = file name of the block without `.liquid`.

- Add app block: `https://{shop}/admin/themes/current/editor?template={template}&addAppBlockId={SHOPIFY_API_KEY}/{block_handle}&target={target}`
  - `target=mainSection` for blocks in the main section (e.g. `mq-price`, `mq-bundle-picker`, `mq-gpsr` on `product`).
  - `target=newAppsSection` for `mq-page-sections` (own section below the main section).
  - Other valid values: `sectionGroup:header|footer|aside`, `sectionId:<id>`.
  - `template` = `product`, `page`, `index`, or a custom template such as `product.mosaiq` / `page.mosaiq` (09).
- Enable app embed: `https://{shop}/admin/themes/current/editor?context=apps&template={template}&activateAppId={SHOPIFY_API_KEY}/{embed_handle}`
- Open via App Bridge (`open(url, "_top")`), not inside the iframe.

## v1.1 additions

See `docs/12-v1.1-store-builder.md` §4 (new scopes write_online_store_navigation and write_publications, webhook products/create, collection/menu/publication/price operations, delivery metafield). That document takes precedence for F15–F18.

### v1.1 verified shapes (T-110, live against dev store, API 2026-07)

All shapes below were verified by running the operation against
`mosaiq-pod.myshopify.com` and recording the response as a fixture in
`tests/fixtures/shopify/` (AGENTS.md §5). Deviations from the docs are
marked.

- **Scopes**: `write_online_store_navigation` (menuCreate/menuUpdate/menuDelete),
  `write_publications` (publishablePublish). The `publications` **query**
  additionally requires `read_publications` — add it to the toml when the
  re-grant is deployed. Existing installs must re-authorise
  (`apps/core/scopes.py`: `check_start_scopes()`, `build_regrant_url()`;
  error code `SCOPE_MISSING`). Granted scopes are read live via
  `currentAppInstallation { accessScopes { handle } }` — never inferred
  from the token.
- **Webhook**: `products/create` added to `shopify.app.toml` topics.
- **`collectionCreate(collection: CollectionCreateInput!)`** — one arg,
  not the legacy `input`. Fields: `title` (required), `handle`,
  `descriptionHtml`, `templateSuffix`, `sortOrder`, `sources`.
  Manual product membership (Q18, verified by live create):
  `sources: [{source: {title: "<label>" (required), inclusion: {matchType: ANY|ALL, selections: [{productId: ID!, variantIds: [ID]}]}}}]`
  — `selections` lives under `inclusion`, NOT directly under `source`.
- **`collectionDelete(input: CollectionDeleteInput!)`** — wrapped input
  arg (deviation: `menuDelete`/`pageDelete` take a bare `id`).
- **`menuCreate(title: String!, handle: String!, items: [MenuItemCreateInput!]!)`**
  — loose top-level args, there is NO `MenuCreateInput` type in 2026-07
  (Q19 duplicate-handle behaviour still blocked on the scope re-grant).
  `menuUpdate(id: ID!, title: String!, items: [MenuItemUpdateInput!]!)`.
  `MenuItemCreateInput`: `title`, `type` (MenuItemType: FRONTPAGE,
  COLLECTION, CATALOG, PAGE, HTTP, …), `resourceId`, `url`, `tags`.
- **`productVariantsBulkUpdate(productId: ID!, variants: [ProductVariantsBulkInput!]!)`**
  — price-only update: pass `{id, price}` per variant; verified live.
- **`node(id:) { ... on ProductVariant { inventoryItem { unitCost { amount currencyCode } } } }`**
  — reads the default supplier cost (scope read_inventory).
- **`publishablePublish(id: ID!, input: [PublicationInput!]!)`** —
  `PublicationInput`: `publicationId`, `publishDate`. Blocked on
  `read_publications`/`write_publications` until re-grant.
- **UserError has NO `code` field** in 2026-07 — only `field` + `message`
  (deviation; several hand-written queries selected `code` and failed).
