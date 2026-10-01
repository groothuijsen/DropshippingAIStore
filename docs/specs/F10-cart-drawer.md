# F10 — Cart drawer with upsells and rewards bar

**References:** 04 §1 (`mq-cart-drawer`), 02 (`Offer` kinds `cart_upsell`, `reward_bar`), 07 §3.

## Acceptance criteria

1. **Given** the embed is on and `enabled`, **when** a shopper clicks an add-to-cart button, **then** the Mosaiq drawer opens with the current cart from `/cart.js`, without a page reload.
2. **Given** the embed is off or `enabled=false`, **then** the store behaves exactly as without Mosaiq.
3. Upsells: 1–3 products chosen by the merchant (`CartUpsellRules`, 04 §3), written as handles to the app-data metafield `cart`; the embed reads them with `all_products[handle]`. A product that is already in the cart is not shown.
4. Rewards bar: thresholds in store currency (e.g. free shipping from €50); text "Nog €X tot …" ("€X more until …") calculated from the cart subtotal; only shown if the reward actually exists (merchant confirms that the shipping rule is configured in Shopify).
5. Shipping protection: **not in MVP** (requires a separate product and legal texts).
6. Changing quantities and removing via `/cart/change.js`; error messages from Shopify (e.g. stock) are shown.
7. Keyboard and screen reader accessible: focus trap in the drawer, Escape closes, `aria-live` for subtotal.
8. Works in Dawn and Horizon; a theme with its own drawer does not show two drawers (Mosaiq intercepts the event; in case of conflict, document it and show instructions to switch off the theme drawer).

## Assumptions made during build
- Implemented as specified; no additional assumptions beyond those recorded in `docs/BUILD_LOG.md`.
