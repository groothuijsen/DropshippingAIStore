# 13 — Marketing site and sales copy (shopify.mosaiq.marketing)

Status: specified 2026-10-01. Build after the v1.1 app tickets (T-110–T-142, doc 12), so the site describes the product as it actually ships. Feature spec: `docs/specs/F19-marketing-site.md`. Copy sources: `docs/marketing/`.

## 1. Current state (what exists)

- `apps/core/salespage.py` serves one English page, `templates/marketing/shopify_salespage.html`, only on host `shopify.mosaiq.marketing`. The embedded app runs on `shop.mosaiq.marketing` (this answers Q8 in open-questions).
- "Get early access" links to `https://mosaiq.marketing`; there is no own sign-up form.
- Problems to fix (all covered by F19):
  1. Copy claims the app "researches products" — Mosaiq does not source products (12 D-15.2); F15 gives product *ideas* only.
  2. Copy says Mosaiq "never stores personal data of your shoppers" — false: `WithdrawalRequest` stores shopper data (07 §8).
  3. FAQ says "any plan that supports custom app installs" — Mosaiq is a public App Store app.
  4. Google Fonts are loaded from Google's servers. In Germany this was ruled a GDPR violation (LG München I, 20 Jan 2022, 3 O 17493/20). Fonts must be self-hosted.
  5. English only; no pricing, no legal pages, no company details, no sitemap, no hreflang.

## 2. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D-19.1 | The site stays in this Django project as a new app `apps/marketing`, host-guarded to `shopify.mosaiq.marketing` exactly like the current salespage. The app host `shop.mosaiq.marketing` never serves marketing routes and vice versa. | One deploy, one stack (HTMX/Alpine, Django templates), no extra service. |
| D-19.2 | Page copy lives in Markdown files with YAML front matter under `content/marketing/<lang>/`, not in templates and not in the database. Templates render sections from front matter keys. UI chrome (nav, footer, buttons) uses Django i18n. | Copy can be edited and reviewed in git without touching code; agents can update content safely. |
| D-19.3 | Languages: `en` (root `/`), `nl` (`/nl/`), `de` (`/de/`). `hreflang` for all three plus `x-default` → `/`. No automatic redirect by browser language; a language switcher instead. | Crawlers and shared links must see stable URLs. |
| D-19.4 | No third-party requests from the marketing site: fonts, scripts, images and analytics are self-hosted. Analytics: self-hosted Plausible or Umami in cookieless mode on the own Proxmox server. With no cookies and no third parties, no cookie banner is needed; the cookie statement says so. | GDPR/ePrivacy; LG München ruling; privacy-first positioning. |
| D-19.5 | Every claim on the site must be true for the shipped version and verifiable. Numbers ("in under 3 minutes", "6 presets") come from `docs/marketing/claims.md`, each with its source (test, spec, measurement). A claim without a source is not published. | Unfair Commercial Practices Directive; the product sells honesty about compliance — the site must meet the same bar. |
| D-19.6 | Comparison content is factual, dated and sourced (Directive 2006/114/EC on comparative advertising: objective, verifiable, not denigrating). Every comparison table shows "Last checked: <date>" and links its sources. Re-check every 90 days (Celery beat reminder to the founder). | Legal requirement and credibility. |
| D-19.7 | Lead capture: own waitlist form on the site with double opt-in. Data stored in the `marketing.Lead` model on the own server; no external form service. | GDPR; no third parties. |
| D-19.8 | Legal pages (privacy policy, terms, DPA, sub-processors, cookie statement, company details) are drafts written from `docs/marketing/legal-outline.md` and carry the draft banner until the lawyer review (T-090 scope extended). Shopify requires a privacy-policy URL in the App Store listing, so these block the listing submission (T-093). | App Store requirement; legal exposure. |

## 3. Site map and routes

All routes exist under `/`, `/nl/` and `/de/` (prefix omitted below). Slugs are translated per language in front matter (`slug_nl`, `slug_de`); the table shows the English slug.

| Route | Page | Content file | Purpose |
| --- | --- | --- | --- |
| `/` | Home | `home.md` | positioning, how it works, features, pricing teaser, FAQ, CTA |
| `/features/` | Features overview | `features.md` | all modules with screenshots |
| `/start-from-zero/` | Start from zero | `start-from-zero.md` | F15 wizard explained (niche → brand → products → store) |
| `/eu-compliance/` | EU compliance | `eu-compliance.md` | Omnibus, unit price, GPSR, withdrawal button, AI labels, green claims, delivery times — the pillar page |
| `/pricing/` | Pricing | `pricing.md` | plans from `apps/billing/plans.py` (rendered from code, not typed) + FAQ |
| `/compare/` | Comparison | `compare.md` | Mosaiq vs AI store builders (dated, sourced) |
| `/agencies/` | Agencies | `agencies.md` | agency plan, multi-store, partner programme |
| `/affiliates/` | Affiliate programme | `affiliates.md` | 30% recurring for 12 months, terms summary |
| `/early-access/` | Waitlist | `early-access.md` | form (D-19.7) until App Store approval, then replaced by "Install on Shopify" |
| `/blog/` + `/blog/<slug>/` | Blog | `blog/<slug>.md` | compliance and store-building articles (briefs in `docs/marketing/blog-briefs.md`) |
| `/help/` + `/help/<slug>/` | Help centre | `help/<slug>.md` | installation (App Store requirement 5.1.3), blocks and templates, start from zero, compliance checklist, billing, uninstall |
| `/changelog/` | Changelog | `changelog.md` | public product changes, newest first |
| `/legal/privacy/`, `/legal/terms/`, `/legal/dpa/`, `/legal/subprocessors/`, `/legal/cookies/`, `/legal/company/` | Legal | `legal/*.md` | D-19.8 |
| `/sitemap.xml`, `/robots.txt` | SEO | generated | all languages, `lastmod` from file mtime in git |
| `/og/<page>.png` | Open Graph images | generated at build | 1200×630, per page and language |

The current `/` salespage is replaced by the new home; its design tokens and layout may be reused.

## 4. Content file format

```markdown
---
title: "AI store builder for European Shopify brands"
description: "…"            # meta description, max 155 characters
slug_nl: "eu-regels"         # only on non-home pages
slug_de: "eu-regeln"
template: "marketing/page_default.html"
sections:
  - type: hero
    eyebrow: "…"
    headline: "…"            # max 70 characters
    sub: "…"                 # max 200 characters
    cta_primary: { label: "…", href: "@install" }   # @install / @early_access resolve in code
    cta_secondary: { label: "…", href: "#how" }
  - type: steps
    items: [ { title: "…", text: "…" } ]
  - type: features
    items: [ { icon: "compliance", title: "…", text: "…", claim_ids: ["C-07"] } ]
  - type: faq
    items: [ { q: "…", a: "…" } ]
  - type: cta
    headline: "…"
---
Optional Markdown body (used by blog, help and legal pages).
```

- Section types are a fixed set with a Pydantic schema each (`apps/marketing/schemas.py`): `hero`, `steps`, `features`, `split` (text + screenshot), `compliance_grid`, `pricing_table` (no copy fields for prices — rendered from `PLAN_LIMITS` and plan prices in code), `comparison` (rows + `last_checked` + `sources`), `faq`, `quote` (only real, attributed quotes with written consent; none at launch), `cta`.
- `claim_ids` link a sentence to `docs/marketing/claims.md`. The build check `manage.py check_marketing_content` fails when a referenced claim is missing, marked `unverified`, or when a file fails its schema or a length limit.
- `@install` resolves to the App Store listing URL once `MARKETING_APP_LISTED=true`, else to `/early-access/`.

## 5. SEO and performance

- One `<h1>` per page; title ≤ 60 characters, description ≤ 155.
- `hreflang` + canonical per language; `x-default` → English.
- Structured data (JSON-LD): `Organization` (with company details), `SoftwareApplication` (with `offers` from plan prices), `FAQPage` on pages with a FAQ section, `BreadcrumbList` on blog and help, `Article` on blog posts.
- Lighthouse mobile ≥ 95 for performance, accessibility, best practices and SEO on home, pricing and one blog post (CI check with the existing Lighthouse script from T-092).
- Images: AVIF/WebP with explicit width/height, screenshots taken from the dev store demo shops (wellness/sleep, car accessories, POD merch). Never use AI-generated images that suggest real customers or real results.
- No JavaScript is required to read any page; HTMX only for forms; Alpine only for the language switcher and FAQ toggles.

## 6. Forms, leads and email

`marketing.Lead`: `email` (unique per `list`), `list` (`early_access`, `newsletter`, `agency`), `locale`, `shop_domain` (optional), `consent_text` (exact text shown), `consent_at`, `confirmed_at` null, `confirm_token` (hashed), `source_page`, `created_at`, `unsubscribed_at` null.

- Double opt-in: confirmation email with a single-use link valid 7 days; unconfirmed leads are deleted after 30 days (beat task).
- Spam protection: honeypot field + rate limit (5 submissions per IP per hour, Redis). No reCAPTCHA or other third-party challenge.
- Every email has an unsubscribe link; unsubscribing sets `unsubscribed_at`, never deletes the consent record.
- Email copy: `docs/marketing/emails.md` (early-access confirmation, launch announcement, and the in-app onboarding sequence).
- Data export and deletion of a lead on request: admin action, logged in `AuditLog`.

## 7. Copy rules (also for agents writing blog posts)

1. Write for EU merchants and agencies; plain language; no hype words ("revolutionary", "#1", "best").
2. Never promise revenue, conversion rates or "winning products".
3. Compliance features: say what Mosaiq does, and that the merchant stays responsible ("helps you meet", never "makes you compliant" or "guarantees compliance").
4. No fake scarcity, countdowns, fake reviews, invented logos or invented user numbers.
5. Prices in USD as billed by Shopify, with "excl. VAT where applicable".
6. Every number links to a claim in `claims.md`.
7. Blog posts by AI agents are drafts until the founder approves them (`draft: true` in front matter keeps them out of the sitemap and lists).

## 8. Open questions

| # | Question | Blocks | Owner |
| --- | --- | --- | --- |
| Q22 | Logo and visual identity for Mosaiq (the current page uses a lime-on-dark wordmark). Keep it, or align with Mosaiq Marketing? | T-151 | Paul |
| Q23 | Company details for `/legal/company/` and the footer: legal entity (BV or sole proprietorship), KvK number, VAT ID, address | T-156 | Paul |
| Q24 | Email sending provider for marketing and onboarding mail (current setting: SMTP via `EMAIL_URL`) — EU-hosted provider preferred | T-155 | Paul |
| Q25 | German copy: native-speaker review before publishing `/de/` | T-158 | Paul |
