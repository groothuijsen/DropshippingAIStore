# F19 — Marketing site and sales copy (shopify.mosaiq.marketing)

**References:** 13 (all sections), `docs/marketing/` (claims, copy, listing, emails, blog briefs, legal outline), F12 (plans), F14 (support), 07 (claims rules), 10 §5 (Lighthouse).

## Acceptance criteria

1. **Hosts.** `apps/marketing` serves all routes of 13 §3 only on `shopify.mosaiq.marketing`; on any other host they return 404. The embedded app on `shop.mosaiq.marketing` is unchanged. The old `apps/core/salespage.py` view and template are removed and `/` is served by `apps/marketing`. Tests cover both hosts.
2. **Content.** Every page renders from `content/marketing/<lang>/*.md` (13 §4). `manage.py check_marketing_content` validates every file against its section schemas and length limits, checks that all three languages have the same set of pages, and that every `claim_ids` entry exists in `docs/marketing/claims.md` with status `verified`. It runs in CI; a failure blocks the merge.
3. **Copy.** The English and Dutch copy from `docs/marketing/site-copy.en.md` and `site-copy.nl.md` is transferred into content files without changing meaning. German is produced from the English master with `LLM_MODEL_COPY` and stays `draft` until Q25 is resolved; until then `/de/` returns 404 and is absent from the sitemap and `hreflang`.
4. **Pricing.** The pricing table is rendered from `apps/billing/plans.py` (prices, limits, trial) — no price or limit is typed in a content file. Prices show in USD with "excl. VAT where applicable" and the annual price.
5. **No third parties.** The rendered HTML of every page contains no request to another host (test: parse all `src`/`href`/`url()` references; only same-host or `apps.shopify.com` links in anchors are allowed). Fonts are self-hosted WOFF2 files in `static/marketing/fonts/` with their OFL licence files.
6. **Analytics.** Self-hosted cookieless analytics (D-19.4) loads from the own host; no marketing page sets a cookie except the CSRF cookie on pages that contain a form (test: anonymous GET of every other page returns no `Set-Cookie` header). The cookie statement lists the CSRF cookie as strictly necessary.
7. **Waitlist.** The early-access form follows 13 §6: double opt-in, honeypot, rate limit, consent text stored verbatim, confirmation email from `docs/marketing/emails.md`, deletion of unconfirmed leads after 30 days. With `MARKETING_APP_LISTED=true` every `@install` CTA links to the App Store listing and the waitlist page shows an install button instead of the form.
8. **SEO.** Each page has one `<h1>`, title ≤ 60 and description ≤ 155 characters, canonical, `hreflang` (only for published languages), JSON-LD per 13 §5, and appears in `sitemap.xml`. `robots.txt` allows all and links the sitemap. Draft blog posts are excluded.
9. **Performance and accessibility.** Lighthouse mobile ≥ 95 in all four categories on home, pricing and one blog post (script from T-092). Keyboard navigation works for the menu, language switcher and FAQ.
10. **Legal.** Legal pages exist in all published languages, carry the draft banner until the lawyer review, and the footer shows company details from settings (Q23). The App Store listing (T-093) uses `/legal/privacy/` as the privacy-policy URL.
11. **Comparison.** `/compare/` shows `last_checked` and sources per row; a beat task emails the founder 90 days after `last_checked`. If `last_checked` is older than 120 days, the comparison section is hidden automatically.
12. **Help centre.** Help articles from 13 §3 exist; the in-app support page (F14) links to them; the App Store listing links the installation article (requirement 5.1.3).
13. **Blog.** Blog list, post template, RSS feed (`/blog/feed.xml`), and the first 6 posts from `docs/marketing/blog-briefs.md` as drafts, written by the founder's content agents and approved before publishing.
14. **Onboarding emails.** The in-app onboarding email sequence from `docs/marketing/emails.md` is sent by Celery beat, only to the merchant's contact email, with an unsubscribe link, and stops when the merchant uninstalls.

## Assumptions made during build
_(to be filled in by Hermes)_
