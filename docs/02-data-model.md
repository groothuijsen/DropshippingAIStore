# 02 — Data model

Conventions for all models:

- Primary key: `id = UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`.
- Timestamps: `created_at = DateTimeField(auto_now_add=True)`, `updated_at = DateTimeField(auto_now=True)`.
- Money: `DecimalField(max_digits=12, decimal_places=2)` + a separate `CharField(max_length=3)` for the currency.
- Shopify IDs: always the full GID as `CharField(max_length=255)`, e.g. `gid://shopify/Product/123`.
- Every table holding shop data has `shop = ForeignKey(Shop, on_delete=CASCADE)` and an index on `shop`.
- `shop/redact` deletes the `Shop` row; CASCADE cleans up the rest. Test this (see F13).

Enums are `models.TextChoices`. The values below are to be used literally.

## core

### `Shop`
| Field | Type | Rules |
| --- | --- | --- |
| `domain` | CharField(255) | unique, `*.myshopify.com`, lowercase |
| `shopify_gid` | CharField(255) | unique |
| `access_token_encrypted` | BinaryField | Fernet; never log; valid for 1 hour |
| `access_token_expires_at` | DateTimeField | |
| `refresh_token_encrypted` | BinaryField | Fernet; rotates on every refresh (03 §2.3a) |
| `refresh_token_expires_at` | DateTimeField | 90 days after the last refresh |
| `needs_reauth` | BooleanField default False | refresh failed; tasks stop until the merchant opens the app |
| `scopes` | CharField(1000) | comma-separated, as received |
| `name` | CharField(255) | |
| `email` | EmailField | merchant contact |
| `primary_locale` | CharField(10) | e.g. `nl` |
| `iana_timezone` | CharField(64) | |
| `currency_code` | CharField(3) | |
| `country_code` | CharField(2) | |
| `ui_locale` | CharField(5) | `nl`/`en`/`de` |
| `status` | TextChoices `ShopStatus` | `active`, `uninstalled`, `frozen` |
| `installed_at` | DateTimeField | |
| `uninstalled_at` | DateTimeField null | |
| `mosaiq_templates_ready` | BooleanField default False | merchant has created `product.mosaiq` and `page.mosaiq` and placed the blocks (09, confirmed with a checkbox) |
| `onboarding_step` | CharField(40) | `language`, `brand`, `sources`, `theme`, `withdrawal`, `done` |
| `import_apps` | JSONField default list | onboarding answers: subset of `dsers`, `cj`, `zendrop`, `autods`, `printify`, `other`, `none` (06 §4.1) |
| `ship_cutoff` | JSONField null | `{"time":"16:00","days":["mon",...],"delivery_days":1}` for the delivery-time notice (07 §3) |
| `guarantee_policy` | TextField blank | filled in by the merchant; source for the `guarantee` section (05 §4.3) |
| `stock_threshold` | PositiveSmallIntegerField default 5 | max. 10 (07 §3) |
| `ai_label_default` | BooleanField default True | default for `Page.ai_image_disclosure` |

### `ShopSession` — not needed. Session tokens are validated per request, not stored.

### `AuditLog`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `actor` | CharField(20) | `merchant`, `system`, `support` |
| `action` | CharField(80) | e.g. `compliance.override_prior_price` |
| `payload` | JSONField | no personal data of shoppers |

## billing

### `Subscription`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | OneToOne Shop | |
| `plan` | TextChoices `Plan` | `starter`, `pro`, `agency` |
| `interval` | TextChoices | `every_30_days`, `annual` |
| `shopify_subscription_gid` | CharField(255) null | |
| `status` | TextChoices | `pending`, `active`, `cancelled`, `declined`, `expired`, `frozen` — mirrors Shopify `AppSubscriptionStatus` in lowercase |
| `trial_ends_at` | DateTimeField null | |
| `current_period_end` | DateTimeField null | |
| `test` | BooleanField | |

### `UsageCounter`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `period_start` | DateField | start of the 30-day period |
| `store_generations` | PositiveIntegerField default 0 | |
| `ai_images` | PositiveIntegerField default 0 | |
| `reserved_store_generations` | PositiveIntegerField default 0 | reserved at job start, released on completion/failure |
| `reserved_ai_images` | PositiveIntegerField default 0 | same |

Live pages are **not** stored but counted live: `Page.objects.filter(shop=shop, status="live").count()`.

Unique constraint: (`shop`, `period_start`). Increment only via `F()` expressions inside a transaction with `select_for_update` on the row.

### `TrialLedger`
| Field | Type | Rules |
| --- | --- | --- |
| `domain_sha256` | CharField(64) | unique; sha256 of the lowercase shop domain |
| `first_trial_at` | DateTimeField | |

**No** FK to `Shop`; persists after `shop/redact` (see 08 §4).

## sources

### `ProductSource`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `product_gid` | CharField(255) | |
| `source` | TextChoices `SourceApp` | `manual`, `dsers`, `cj`, `zendrop`, `autods`, `printify`, `printful`, `unknown_app` |
| `detected_by` | CharField(40) | `mosaiq` (created by Mosaiq), `fulfillment_location`, `onboarding`, `vendor`, `sku`, `merchant` |
| `created_by_mosaiq` | BooleanField default False | only True after `product_create_manual`; the sole condition for full write access (06 §2) |
| `locked_fields` | JSONField | list of field names that Mosaiq never writes (see 06) |

Unique: (`shop`, `product_gid`).

## themes

### `BrandKit`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | OneToOne Shop | |
| `brand_name` | CharField(80) | |
| `tone` | TextChoices | `warm`, `premium`, `playful`, `clinical`, `sporty` |
| `palette` | JSONField | `{"primary":"#RRGGBB","secondary":...,"accent":...,"background":...,"text":...}` — hex validated, text/background contrast ≥ 4.5:1 |
| `font_heading` | CharField(40) blank | key from the bundled font list (04 `mq-tokens`); empty = inherit the theme font |
| `font_body` | CharField(40) blank | same |
| `style_preset` | TextChoices `StylePreset` | `clean`, `bold`, `organic`, `luxe`, `tech`, `soft` |
| `logo_file_gid` | CharField(255) null | Shopify File GID |
| `tokens_synced_at` | DateTimeField null | last `metafieldsSet` of the tokens |

## generator

### `GenerationJob`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `kind` | TextChoices | `store`, `page` |
| `parent` | FK self null | for `kind=store`: the three child jobs (home, pdp, about) reference the store job |
| `page_type` | TextChoices `PageType` null | `pdp`, `landing`, `advertorial`, `listicle`, `home`, `about` (null only for `kind=store`) |
| `saved_template` | FK SavedTemplate null | F08 |
| `content_locale` | CharField(5) | |
| `input` | JSONField | `JobInput.model_dump(mode="json")` (05); read back with `model_validate` |
| `status` | TextChoices `JobStatus` | `queued`, `running`, `needs_input`, `succeeded`, `failed`, `cancelled` |
| `current_step` | CharField(40) null | |
| `error_code` | CharField(60) null | see error codes in 05 |
| `error_message` | TextField null | for the merchant, translated |
| `ai_cost_usd` | DecimalField(10,4) default 0 | sum of the steps |
| `started_at` / `finished_at` | DateTimeField null | |
| `idempotency_key` | CharField(64) | unique per shop; prevents duplicate jobs on double-click |

### `JobStep`
| Field | Type | Rules |
| --- | --- | --- |
| `job` | FK GenerationJob | |
| `name` | TextChoices `StepName` | `import`, `research`, `copy`, `images`, `compliance_check`, `layout`, `publish` |
| `status` | TextChoices | `pending`, `running`, `succeeded`, `failed`, `skipped` |
| `attempt` | PositiveSmallIntegerField default 0 | |
| `output` | JSONField null | validated output of the step (checkpoint) |
| `ai_cost_usd` | DecimalField(10,4) default 0 | |
| `started_at` / `finished_at` | DateTimeField null | |

Unique: (`job`, `name`). A step with status `succeeded` is skipped on restart (checkpoint).

### `AiCall`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | CASCADE; also for calls outside a job |
| `step` | FK JobStep null | null for palette, rewrite, translate |
| `purpose` | CharField(40) | `research`, `copy`, `image`, `fidelity`, `compliance`, `url_facts`, `palette`, `rewrite`, `translate`, `shot_plan` |
| `provider` | CharField(20) | `anthropic`, `vertex`, `openai` |
| `model` | CharField(80) | |
| `input_tokens` / `output_tokens` | PositiveIntegerField | |
| `images` | PositiveSmallIntegerField default 0 | |
| `cost_usd` | DecimalField(10,4) | |
| `duration_ms` | PositiveIntegerField | |
| `success` | BooleanField | |

### `Page`
Created directly after the `copy` step (status `draft`, nothing in Shopify yet), so that the editor and `ClaimFinding` always have a page.

| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `job` | FK GenerationJob null | |
| `page_type` | PageType | |
| `title` | CharField(120) | internal and Shopify page title |
| `angle` | CharField(120) | chosen angle |
| `content_locale` | CharField(5) | primary language |
| `sections` | JSONField | `SectionsPayload` per language: `{"nl": {...}, "de": {...}}`; source of truth for the editor |
| `images` | JSONField default dict | `{"hero": "gid://shopify/MediaImage/…", "lifestyle_1": …}` per slot |
| `seo_title` / `seo_description` | CharField(60) / CharField(155) | primary language (per language in `sections`) |
| `ai_image_disclosure` | BooleanField | default `Shop.ai_label_default` |
| `product_gid` | CharField(255) null | for `pdp` |
| `shopify_page_gid` | CharField(255) null | for `landing`/`advertorial`/`listicle`/`about` |
| `shopify_page_handle` | CharField(255) null | |
| `metaobject_handles` | JSONField default dict | per language: `{"nl": "mq-3fa9c21b-5d1e8a0f-nl"}` = `mq-<shop-short>-<page-uuid-8>-<lang>`; `shop-short` = first 8 characters of sha256(shop domain); `<lang>` = language |
| `metaobject_gids` | JSONField default dict | per language |
| `version` | PositiveIntegerField default 0 | +1 on every publication to Shopify (draft or live) |
| `status` | TextChoices | `draft`, `live`, `archived` |
| `compliance_score` | PositiveSmallIntegerField default 0 | 0–100 (07) |
| `variant_of` | FK self null | for A/B in v1.1 |

## offers

### `Offer`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `kind` | TextChoices `OfferKind` | `volume`, `bogo`, `free_gift`, `cart_upsell`, `reward_bar` |
| `labels` | JSONField | per language: `{"nl": "Bundelkorting"}`; max. 50 characters |
| `title` | CharField(120) | internal |
| `product_gids` | JSONField | list of GIDs to which the offer applies |
| `rules` | JSONField | validated with `offers.schemas.OfferRules` (04 §3) |
| `starts_at` | DateTimeField | |
| `ends_at` | DateTimeField null | **only filled if the offer actually ends**; precondition for a timer |
| `show_timer` | BooleanField default False | may only be True if `ends_at` is filled (model `clean()` + DB CheckConstraint) |
| `shopify_discount_gid` | CharField(255) null | automatic discount used by the Function |
| `status` | TextChoices | `draft`, `active`, `inactive` (manually deactivated), `ended` (end date passed) |
| `metaobject_handle` | CharField(80) | `mq-offer-<offer-uuid-8>` |

A maximum of **20** active Mosaiq discounts per shop. Shopify allows **25 active automatic discounts per shop**, **including those of other apps**; before activating, `offers.shopify.count_active_automatic()` counts all active automatic discounts and refuses at ≥ 25 with a clear message. Only `volume`, `bogo` and `free_gift` use a discount.

CheckConstraint: `show_timer = False OR ends_at IS NOT NULL`.

## compliance

### `PriceHistory`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `variant_gid` | CharField(255) | |
| `market_handle` | CharField(80) default `primary` | per Shopify Market if prices differ per market |
| `price` | DecimalField | |
| `currency` | CharField(3) | |
| `observed_at` | DateTimeField | |
| `source` | CharField(20) | `install_snapshot`, `webhook`, `daily_snapshot`, `merchant_attested` |

Index: (`shop`, `variant_gid`, `market_handle`, `observed_at`). Rows older than 400 days are deleted by a beat task.

### `PriceAttestation`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `variant_gid` | CharField(255) | |
| `lowest_price_30d` | DecimalField | provided by the merchant |
| `valid_until` | DateTimeField | installation + 30 days; after that only real history applies |

### `GpsrInfo` (per product)
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `product_gid` | CharField(255) | unique per shop |
| `manufacturer_name` | CharField(200) | required |
| `manufacturer_address` | TextField | required, postal address |
| `manufacturer_email` | EmailField | required |
| `manufacturer_in_eu` | BooleanField | |
| `eu_rp_name` / `eu_rp_address` / `eu_rp_email` | fields, null | required if `manufacturer_in_eu = False` |
| `product_identifier` | CharField(200) | type/model/batch |
| `warnings` | JSONField | `{"nl": "...", "en": "...", "de": "..."}`; empty string allowed if no warning applies, provided `no_warnings_confirmed = True` |
| `no_warnings_confirmed` | BooleanField default False | |
| `complete` | BooleanField | computed in `save()` |

### `UnitPriceInfo` (per variant)
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `variant_gid` | CharField(255) | unique per shop |
| `net_quantity` | DecimalField(10,3) | e.g. `30.000` |
| `unit` | TextChoices | `g`, `kg`, `ml`, `l`, `cm`, `m`, `m2`, `m3` |
| `applies` | BooleanField | False = no unit price obligation (e.g. textiles) |

### `ClaimFinding`
| Field | Type | Rules |
| --- | --- | --- |
| `page` | FK Page | |
| `locale` | CharField(5) | |
| `section_index` | PositiveSmallIntegerField | 0-based index into `sections[locale].sections` |
| `field_path` | CharField(80) | e.g. `headline`, `items.2.text` |
| `source` | TextChoices | `regex`, `ai` |
| `rule_id` | CharField(40) | from 07 §4.1 |
| `severity` | TextChoices | `block`, `warn` |
| `excerpt` | CharField(300) | |
| `suggestion` | TextField | |
| `resolved` | BooleanField default False | |
| `override_reason` | TextField null | only for `warn`; `block` cannot be overridden |

## templates_lib

### `SavedTemplate`
| Field | Type | Rules |
| --- | --- | --- |
| `owner_shop` | FK Shop | |
| `name` | CharField(120) | |
| `page_type` | PageType | |
| `structure` | JSONField | section order + block settings, **without** product-specific text or prices |
| `shared_with_account` | BooleanField default False | available to other shops of the same Shopify organization (v1.2; MVP: own shop only) |

## analytics

### `Event`
| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `name` | CharField(60) | `installed`, `job_started`, `job_succeeded`, `page_published`, `offer_activated`, `trial_started` (on subscription approval), `plan_changed`, `uninstalled` |
| `properties` | JSONField | no personal data |
| `occurred_at` | DateTimeField | |

## compliance (continued): withdrawal

### `WithdrawalRequest`
The only table containing personal data of shoppers (AGENTS.md §2). Retention period 2 years (a beat task deletes them afterwards).

| Field | Type | Rules |
| --- | --- | --- |
| `shop` | FK Shop | |
| `reference` | CharField(20) | unique, e.g. `MQW-7F3K9Q`; shown to the customer |
| `customer_name` | CharField(200) | as entered |
| `order_identifier` | CharField(100) | order number as entered (not validated against Shopify; no `read_orders`) |
| `email` | EmailField | for the confirmation |
| `locale` | CharField(5) | |
| `submitted_at` | DateTimeField | time of step 2 (confirm) = legally effective moment |
| `confirmation_sent_at` | DateTimeField null | confirmation to the customer |
| `merchant_notified_at` | DateTimeField null | |
| `status` | TextChoices | `submitted`, `handled` (marked by the merchant) |

`customers/redact` deletes rows with the same email address; `customers/data_request` exports them to the merchant.

## webhooks

### `WebhookReceipt`
| Field | Type | Rules |
| --- | --- | --- |
| `webhook_id` | CharField(100) | unique (`X-Shopify-Webhook-Id`) |
| `topic` | CharField(80) | |
| `shop_domain` | CharField(255) | |
| `received_at` | DateTimeField | |
| `processed` | BooleanField default False | |

Delete rows older than 30 days via a beat task.

## v1.1 additions

See `docs/12-v1.1-store-builder.md` §2 (BusinessDetails, StoreBlueprint, ManagedResource, DeliveryProfile/DeliveryOverride, PageEdit, PricingSettings/PriceAdvice, and changes to Shop, Page, GenerationJob, UsageCounter). That document takes precedence for F15–F18.
