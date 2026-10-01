# Claims register

Every factual statement on the marketing site, in the App Store listing and in emails refers to a claim ID below (13 §4, §7). Status `verified` = the source exists and the shipped version meets it. Only `verified` claims may be published; `check_marketing_content` enforces this.

| ID | Claim (EN) | Source | Status | How to verify |
| --- | --- | --- | --- | --- |
| C-01 | Copy written natively in Dutch, English and German | F03, i18n | verified after T-158 | evalset language check (F03-4) |
| C-02 | 6 style presets, 6 bundled fonts | F05, `themes/presets.py`, `themes/fonts.py` | verified | count in code |
| C-03 | A complete product page in a few minutes | 05, job durations | **unverified** | median `GenerationJob` duration for `pdp` over the evalset; publish "in about N minutes" with N = rounded-up median |
| C-04 | Flat monthly price: no usage charges, no revenue caps, no per-order fees | 08 §1 | verified | `PLAN_LIMITS`, Billing API line items |
| C-05 | Mosaiq never writes theme files | 00, AGENTS.md §2 | verified | no `write_themes` scope in `shopify.app.toml` |
| C-06 | Uninstalling leaves no Mosaiq code in your theme | F13, Shopify removes app blocks | verified after T-084 checklist | manual uninstall test on Dawn and Horizon |
| C-07 | Strikethrough prices follow the EU 30-day lowest-price rule | F11-A, 07 §1 | verified | test cases 07 §1.4 |
| C-08 | Unit price per bundle tier where required | F09-3, F11-B | verified | F09 tests |
| C-09 | Countdown timers only for offers with a real end date | F09-5, 07 §3 | verified | model + DB constraint |
| C-10 | Product safety (GPSR) information block per product | F11-E | verified | T-082 |
| C-11 | AI images get a visible label and machine-readable marking (C2PA) | F04, 07 §6 | verified (C2PA on CDN variants: see Q3) | T-042, T-043 |
| C-12 | Withdrawal ("cancel contract") link and guest form | F11-G, 07 §8 | verified after T-090 legal review | T-088 |
| C-13 | Blocks generic green claims such as "eco-friendly" before publishing | 07 §4.1 | verified | claim check tests |
| C-14 | Works on top of DSers, CJ, Zendrop, AutoDS and Printify without touching what they manage | 06 | **partly verified**: per app after its fixture (Q17) | list only apps with a recorded fixture |
| C-15 | Shows delivery times per market on the product page | F18 | verified after T-141 | F18 tests |
| C-16 | Price advice including VAT per EU country | F17 | verified after T-130 | F17 test cases |
| C-17 | Start from zero: 8 brand-name ideas, brand kit, 5–10 product ideas, collections, menu and standard pages | F15 | verified after T-118 | F15 tests |
| C-18 | 7-day free trial | 08 | verified | Billing API `trialDays` |
| C-19 | Change pages in plain language, with a before/after view | F16 | verified after T-121 | F16 tests |
| C-20 | Your store keeps working if Mosaiq is down | 00, 04 (storefront runs on Shopify) | verified | architecture |
| C-21 | Billing through your Shopify invoice | 08 | verified | Billing API |
| C-22 | App data stored on servers in the EU | 11-ops | **unverified** | confirm server location; note that AI providers process prompts (sub-processor list) — never say "all data stays in the EU" |
| C-23 | Prices $29 / $59 / $149 per month, annual = 10 months | 00, 08 | verified | rendered from code, never typed |
