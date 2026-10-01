# 09 — UI: screens, routes and HTMX

All admin routes under `/app/`, embedded in Shopify, secured by `SessionTokenMiddleware`. Layout: Polaris web components (`<s-page>`, `<s-section>`, `<s-button>` etc.; verify tag names during T-003) + HTMX for partial updates. Navigation via App Bridge `<s-app-nav>` (or `ui-nav-menu`, depending on the App Bridge version; verify during T-003).

Conventions:
- Product IDs in URLs are always numeric (`<int:product_id>`); the view builds the GID `gid://shopify/Product/<id>`. Never a GID in a URL path.
- Full page loads without a valid `id_token` show the bounce page (03 §2.1), never a 401.
- Full pages: `templates/app/<screen>.html`. Partials: `templates/app/partials/<screen>__<part>.html`.
- Every view that returns a partial checks `request.headers.get("HX-Request")`; without that header, it returns the full page.
- Forms: Django Forms, server-side validation, errors returned as a partial with `hx-swap="outerHTML"`.
- Do not calculate amounts or statuses in JS; the server renders everything.
- Usable on mobile (Shopify app on phone): single column below 768 px.

## Navigation (main menu)

Dashboard · Generate · Pages · Offers · Products (compliance) · Settings · Subscription

## Routes

| Route | View | Screen / purpose |
| --- | --- | --- |
| `GET /app/` | `core.views.home` | Redirect to onboarding (if not `done`) or dashboard |
| `GET/POST /app/onboarding/<step>/` | `core.views.onboarding` | Steps `language` → `brand` → `sources` → `theme` → `withdrawal` → `done` |
| `GET /app/dashboard/` | `core.views.dashboard` | Counters (limits), latest jobs, checklist of open items (GPSR, blocks placed, withdrawal) |
| `GET /app/generate/` | `generator.views.start` | Choice: existing product / manual / URL; page type or complete store |
| `POST /app/generate/` | `generator.views.create_job` | Creates `GenerationJob` (idempotency key from hidden field), starts `run_job`, redirects to status |
| `GET /app/jobs/<uuid>/` | `generator.views.job_detail` | Status page with steps |
| `GET /app/jobs/<uuid>/status/` | partial `job__steps` | HTMX poll `hx-trigger="every 3s"`; stops (no more trigger in the partial) on `succeeded`/`failed`/`needs_input`/`cancelled` |
| `GET/POST /app/jobs/<uuid>/angle/` | `generator.views.pick_angle` | 3 angles as cards; the choice resumes the job |
| `POST /app/jobs/<uuid>/cancel/` | | Cancels (Celery revoke + status) |
| `GET /app/pages/` | `generator.views.page_list` | Table: title, type, language, status, compliance score, actions |
| `GET /app/pages/<uuid>/` | `generator.views.page_editor` | Sections on the left (editable fields per section), preview on the right; compliance panel with findings |
| `POST /app/pages/<uuid>/sections/<idx>/` | partial `page__section` | Save section; reruns the deterministic claim check |
| `POST /app/pages/<uuid>/sections/<idx>/rewrite/` | partial | AI rewrites one section using the suggestion (does not count as a generation) |
| `POST /app/pages/<uuid>/findings/<id>/override/` | partial | Only `warn`, reason required |
| `POST /app/pages/<uuid>/recheck/` | | After editing on `needs_input`: reset `compliance_check`/`layout`/`publish` and resume the job (05 §1) |
| `POST /app/pages/<uuid>/translate/<locale>/` | | Generates the sections in an additional store language (F03-6) |
| `GET/POST /app/jobs/<uuid>/confirm-product/` | | Prefilled `ManualProduct` form after URL import (05 §4.1) |
| `POST /app/pages/<uuid>/publish/` | | Writes/updates draft in Shopify |
| `POST /app/pages/<uuid>/go-live/` | | Metaobject `ACTIVE`, page `isPublished:true`; button disabled with explanation if publication requirements (07 §9) are not met |
| `GET /app/pages/<uuid>/place/` | | Shows deep links "Blok toevoegen aan producttemplate" ("Add block to product template") (03 §7) with step-by-step explanation |
| `POST /app/pages/<uuid>/save-template/` | | Create `SavedTemplate` |
| `GET /app/offers/` | `offers.views.list` | Offers with status |
| `GET/POST /app/offers/new/<kind>/` and `/app/offers/<uuid>/` | `offers.views.edit` | Editor per kind; live preview of tiers with unit price; timer toggle only active if end date is filled in |
| `POST /app/offers/<uuid>/activate/` and `/deactivate/` | | Creates/deletes Shopify discount + metaobject |
| `GET /app/products/` | `compliance.views.products` | Product list with source (06), GPSR status, unit price status |
| `GET/POST /app/products/<int:product_id>/gpsr/` | `compliance.views.gpsr` | GPSR form; "kopieer van ander product" ("copy from another product") |
| `GET/POST /app/products/<int:product_id>/unit-price/` | `compliance.views.unit_price` | Per variant net content + unit, or "niet van toepassing" ("not applicable") |
| `GET/POST /app/products/<int:product_id>/prior-price/` | `compliance.views.attestation` | Only during the first 30 days after installation: enter lowest price + confirm |
| `GET/POST /app/settings/brand/` | `themes.views.brand` | BrandKit; preview of tokens; "sync naar winkel" ("sync to store"); recommended fonts + deep link to the `mq-tokens` settings (the merchant chooses fonts there) |
| `GET/POST /app/settings/store/` | `core.views.store_settings` | `guarantee_policy`, `ship_cutoff`, `ai_label_default`, `stock_threshold` (02 `Shop`); saving also writes the app-data metafield `settings` (03 §5.2) |
| `GET /app/settings/withdrawal/` | `compliance.views.withdrawal` | Checklist (07 §8.4) + deep link embed + list of received withdrawals (`WithdrawalRequest`) with button "Afgehandeld" ("Handled") |
| `GET/POST /proxy/withdraw/` | `compliance.views.withdraw_proxy` | **Storefront** via app proxy (`/apps/mosaiq/withdraw`): step 1 form, step 2 confirm, step 3 thank you (07 §8.3). Validation of the proxy `signature`; no session token; Liquid response (`Content-Type: application/liquid`) so that the page appears in the theme layout |
| `GET /app/billing/` | `billing.views.plans` | Plans, current plan, counters, cancel |
| `POST /app/billing/subscribe/<plan>/<interval>/` | | `subscription_create`, redirect to `confirmationUrl` |
| `GET /app/billing/return/` | | After approval: fetch status, forward to dashboard |
| `POST /app/billing/cancel/` | | Cancel |
| `GET /app/support/` | `support.views.index` | Contact form (email to support), status page link, FAQ |

## Screen details that prevent errors

### Onboarding `theme` step
The App Store rules prohibit an app from having merchants download a theme (themes only via the Theme Store, requirement 1.1.3) and require theme app extensions for everything on the storefront (requirement 5.1.1). There is therefore **no** Mosaiq theme. Two levels:

1. **Quick start (default):** buttons with deep links (03 §7) that add `mq-page-sections` to `product` and `index`, `mq-price`, `mq-bundle-picker` and `mq-gpsr` to `product`, and enable the embeds `mq-tokens`, `mq-cart-drawer` and `mq-withdrawal-link`. Blocks without content render nothing, so this is safe for all products.
2. **Mosaiq templates (recommended for landing pages, advertorials and listicles):** guided steps with screenshots per theme (Dawn, Horizon):
   1. Open the theme editor → template selector → Pages → "Nieuwe template maken" ("Create template"), name `mosaiq`, based on the default.
   2. Same for Products, name `mosaiq`.
   3. Deep links with `template=page.mosaiq` and `template=product.mosaiq` to add `mq-page-sections` (and for `product.mosaiq` also `mq-price`, `mq-bundle-picker`, `mq-gpsr`). In those templates the merchant can remove the theme's default sections for a clean landing page.
   4. Checkbox "Templates aangemaakt en blokken geplaatst" ("Templates created and blocks placed") → `Shop.mosaiq_templates_ready = True` (logged in `AuditLog`).
   Mosaiq then sets `templateSuffix = "mosaiq"` on its pages and products. If the template does not exist in the active theme (theme switched), Shopify shows the default template; nothing breaks.

Mosaiq cannot see whether a block has actually been placed (no `read_themes`). Therefore, after clicking, show a checkbox "Gedaan" ("Done") per block and a link to the storefront to verify. App Store requirement 5.1.3 requires detailed installation instructions: this screen plus a help article.

### Job status
- Steps as a list with an icon per status; on `failed` the translated error message from 05 §5 and a button "Opnieuw proberen" ("Try again") (resumes from the failed step).
- On `needs_input` caused by compliance: button to the editor with the compliance panel open.

### Page editor
- The preview renders server-side with the same Liquid-like structure as the blocks (Django templates in `templates/preview/sections/<type>.html`), styled with the design tokens. It is an approximation; show "Voorbeeld — de echte weergave hangt af van je thema" ("Preview — the actual display depends on your theme").
- Publish buttons show the missing requirements as a list (GPSR, unit price, open blockers, limit).

### Offer editor
- Tiers: quantity + percentage; live table with tier total, savings relative to the current unit price, unit price.
- Timer: toggle disabled with the explanation "Alleen mogelijk als het aanbod echt eindigt; vul een einddatum in" ("Only possible if the offer genuinely ends; enter an end date") until `ends_at` is filled in.
- No field for an "original price": it always comes from the variant.

## v1.1 additions

See `docs/12-v1.1-store-builder.md` §6 (wizard, settings and editor routes). That document takes precedence for F15–F18.
