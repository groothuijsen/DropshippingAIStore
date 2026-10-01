# Open questions

Hermes: do not build anything that depends on an open question until it has been answered. Work on another ticket in the meantime.

Researched on 30 September 2026. Answered questions remain listed so that it is clear where a choice comes from.

## Still open

| # | Question | Blocks | Who | Status |
| --- | --- | --- | --- | --- |
| Q3 | Is C2PA preserved on the original in Shopify Files and on CDN variants (`?width=…&format=webp`)? No source found; assumption is "no" for variants. | T-043 (not blocking: SynthID + label cover it) | Hermes tests with `c2patool` | open |
| Q7 | Lawyer review: compliance module, legal templates, terms, provider role under the AI Act, withdrawal labels incl. Belgium | launch | Paul + lawyer | open |
| Q12b | Is `gemini-3.1-flash-image` really on the EU endpoint (`location=eu`)? Google docs did not load; one external source reports GA in EU since 31-08-2026. Check in the Vertex Model Garden. If not: `global` + note about data residency. | T-040 | Hermes | open |
| Q15 | OpenAI EU data residency (`eu.api.openai.com`) requires approval for enhanced ZDR/abuse monitoring and costs ±10% more. Apply for it? | fallback provider, not blocking | Paul | open |
| Q16 | Belgium: transposition of the withdrawal button unclear (sources contradict each other). | T-090 | lawyer | open |
| Q17 | Exact name/handle of the CJdropshipping fulfillment location and the handle of Printify, AutoDS and Zendrop | T-020 (not blocking: onboarding question covers it) | Hermes tests (06 §4.4) | open |
| Q14b | Do app metaobject definitions (`$app:`) remain after uninstall? Docs say metafield definitions are deleted; forum report (2025) says metaobject definitions remained. | T-084 | Hermes tests — dev store `mosaiq-pod.myshopify.com` now available (2026-10-01); uninstall/reinstall test still to run | open |

## Answered

| # | Question | Answer | Consequence in the docs | Source |
| --- | --- | --- | --- | --- |
| Q1 | Let merchants upload our own Mosaiq theme? | **No.** App Store requirement 1.1.3: an app may not let merchants download a theme (only via the Theme Store); requirement 5.1.1: changes to the theme only via theme app extensions. Partner support cannot grant an exception to this. | No own theme; merchant creates `product.mosaiq`/`page.mosaiq` in the theme editor (09, 00). T-100 dropped. | [App Store requirements](https://shopify.dev/docs/apps/launch/shopify-app-store/app-store-requirements), [Built for Shopify](https://shopify.dev/docs/apps/launch/built-for-shopify/requirements) |
| Q2 | Which image model? | `gemini-3.1-flash-image` (GA), escalation `gemini-3-pro-image`, fallback `gpt-image-2.5-sunburst`. Preview IDs have been switched off. ±$0.067 (1K) to $0.10 (2K) per image. | 00, 01, 05 §4.4, `.env.example` | [Gemini models](https://ai.google.dev/gemini-api/docs/models), [Vertex pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing), [OpenAI models](https://developers.openai.com/api/docs/models) |
| Q4 | Expiring offline tokens? | **Mandatory** for public apps created on/after 1 April 2026. `expiring=1`; access token 1 hour, refresh token 90 days, rotates on every refresh. | 03 §2.3/§2.3a, 02 `Shop`, F00-10, T-002 | [Offline access tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/offline-access-tokens) |
| Q5 | Set return settings via API? | **No**, cannot be read or set. | 07 §8.4 (checklist remains manual) | [community.shopify.dev #17455](https://community.shopify.dev/t/store-returns-setting-api/17455) |
| Q8 | Domain name for the app | **Answered 2026-10-01:** app on `shop.mosaiq.marketing`, marketing site on `shopify.mosaiq.marketing`. Both live behind Traefik CT 202 with Let's Encrypt. | Host-guarded routes in `apps/core/` (salespage view) + Traefik `apps.yml`. | deployed infrastructure |
| Q6 | Label text of the withdrawal button | DE: "Vertrag widerrufen" / "Widerruf bestätigen" (§ 356a BGB). EN: "Withdraw from contract here" / "Confirm withdrawal" (directive). NL: no fixed wording (art. 6:230oa BW); chosen "Hier de overeenkomst ontbinden" ("Withdraw from the contract here") / "Ontbinding bevestigen" ("Confirm withdrawal"). DE in principle does not allow a login → guest form moved to MVP. | 07 §8, 04, 03 §5.2, F11-14/17–20, T-088 | [Directive 2023/2673](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32023L2673), [Bitkom](https://www.bitkom.org/sites/main/files/2026-05/bitkom-praxisleitfaden-zur-umsetzung-des-widerrufsbuttons.pdf), [Thuiswinkel.org](https://www.thuiswinkel.org/kennisbank/kennisartikelen/de-herroepingsfunctie-op-weg-naar-implementatie-in-nederland/) |
| Q9 | Source signals of dropship apps | Fulfillment location is the strongest signal (DSers handle `dsers-fulfillment-service` confirmed); vendor at DSers/Printful is the store name; no standard tags; metafields of other apps are unreadable. | 06 §4, 02 `ProductSource`, scope `read_inventory` | help centers of DSers, Printify, Printful, Zendrop, AutoDS (links in 06) |
| Q10 | Scope for `pageCreate` | `write_online_store_pages` (or `write_content`). Metaobject scopes not needed for own `$app:` types since 2026-04. | 03 §1 (scopes reduced) | [Changelog](https://shopify.dev/changelog/metaobject-scopes-not-required-for-app-metaobjects) |
| Q11 | `$app:mosaiq` in Liquid? | **Yes**, documented: `product.metafields["$app:mosaiq"].page.value`. | 03 §5.3; `render_namespace.py` and env variable dropped | [Data ownership](https://shopify.dev/docs/apps/build/custom-data/ownership) |
| Q12 | `app.metafields` in blocks? | Documented, but reports of empty output. | Replaced by shop metafields in `$app:mosaiq` (03 §5.2) | [Liquid `app`](https://shopify.dev/docs/api/liquid/objects/app) |
| Q13 | Discount limit and field names | 25 active automatic discounts per shop, including other apps. `discountClasses` and `functionHandle` exist; `functionId` deprecated in 2026-07. Target `cart.lines.discounts.generate.run`. | 04 §2, 02 `Offer`, F09-2 | [discountAutomaticAppCreate](https://shopify.dev/docs/api/admin-graphql/latest/mutations/discountAutomaticAppCreate), [Help Center](https://help.shopify.com/en/manual/discounts/discount-methods/automatic-discounts) |
| Q14 | What remains after uninstall? | Blocks disappear automatically from the theme; metafield definitions are deleted, values temporarily retained and reattached on reinstall (new IDs). | 03 §3, F00-8, F13-3 | [Metafield definitions](https://shopify.dev/docs/apps/build/metafields/definitions) |
| — | Font picker in app extensions | Does not work reliably (fonts do not load in the editor). | Bundled OFL fonts in `mq-tokens` (04) | [community.shopify.dev #12948](https://community.shopify.dev/t/font-picker-and-app-metadata-inside-theme-extesion-settings/12948) |

## v1.1 (from 12 §9)

| # | Question | Blocks | Owner | Status |
| --- | --- | --- | --- | --- |
| Q18 | Exact shape of `CollectionCreateSourceTargetInput` (manual products in `sources`) in API 2026-07 | T-117 | Hermes (fixture) | open |
| Q19 | Does `menuCreate` fail when a menu with the same handle exists, or auto-suffix the handle? | T-117 | Hermes (fixture) | open |
| Q20 | Can the theme editor be deep-linked to the header section of the active theme for menu selection (Dawn, Horizon)? | T-118 | Hermes | open |
| Q21 | Is a domain check via RDAP from the production server acceptable without rate-limit issues? | T-112 | Hermes | open |

## v1.2 (from 13 §8)

Q8 (app domain) is answered: app on `shop.mosaiq.marketing`, marketing site on `shopify.mosaiq.marketing`.

| # | Question | Blocks | Owner | Status |
| --- | --- | --- | --- | --- |
| Q22 | Logo and visual identity (keep the current lime-on-dark wordmark or align with Mosaiq Marketing?) | T-151 | Paul | open |
| Q23 | Company details for footer and `/legal/company/`: legal entity, KvK number, VAT ID, address | T-156 | Paul | open |
| Q24 | Email provider for marketing and onboarding mail (EU-hosted preferred) | T-155 | Paul | open |
| Q25 | Native German review before `/de/` goes live | T-158 | Paul | open |
