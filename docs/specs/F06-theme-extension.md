# F06 — Theme App Extension and placement

**References:** 04 §1, 03 §5.3 and §7, 09 (onboarding `theme`, `/app/pages/<uuid>/place/`), open-questions Q1 (answered: no own theme).

## Acceptance criteria

1. The extension contains the blocks `mq-page-sections` (templates product, page, index), `mq-bundle-picker`, `mq-gpsr`, `mq-price` and the embeds `mq-tokens`, `mq-cart-drawer`, `mq-withdrawal-link` with schemas according to 04. Metafields via `["$app:mosaiq"]` (03 §5.3).
2. Every block renders nothing (empty, no error) if the corresponding metafield/metaobject is missing.
3. Deep links open the theme editor with the block added to the correct template (product/page) in Dawn and Horizon.
4. All texts come from `locales/*.json`; NL/EN/DE present; a missing key = CI error (script that compares keys).
5. JS per block ≤ 30 KB minified; no external requests except `/cart*.js` and the app proxy.
6. After uninstalling the app, the blocks no longer show anything and the templates do not break (manual check).
7. `mq-page-sections` renders all section types from 05 §3 with accessible markup (heading hierarchy, alt texts, FAQ as `<details>`).
8. There is no own Mosaiq theme (App Store requirement 1.1.3). The guided steps for `product.mosaiq`/`page.mosaiq` (09) and the deep links with those templates work in Dawn and Horizon.
9. `mq-tokens` loads only bundled fonts from the extension assets (no external font services); font `null` → theme font.

## Assumptions made during build
- **Fonts:** Shopify's font picker in app extensions is unreliable (community reports), so `mq-tokens` ships bundled OFL fonts and exposes them as CSS custom properties (open-questions "Font picker" row).
