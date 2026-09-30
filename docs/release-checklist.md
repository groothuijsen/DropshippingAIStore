# Release Checklist — Mosaiq

See docs/10-testing.md §5. Run this checklist on the dev store with both Dawn and Horizon themes before every release.

## 1. Install & Onboarding
- [ ] Install app → onboarding wizard completes
- [ ] Choose plan (test mode) → trial active
- [ ] Trial countdown visible in dashboard

## 2. Import & Product
- [ ] Import product with DSers (test product) → source shown correctly
- [ ] Import product with Printify (test product) → source shown correctly
- [ ] Locked fields show lock icon and cannot be edited

## 3. Generation & Publish
- [ ] Generate PDP in NL → angles shown, choose one
- [ ] Editor loads with all sections
- [ ] Resolve a compliance block (if any)
- [ ] Fill in GPSR data
- [ ] Publish draft → page appears in Shopify
- [ ] Set page live → visible on storefront

## 4. Theme Blocks
- [ ] Add blocks via deep links (bundle picker, offer timer, cart drawer, withdrawal link)
- [ ] Page looks good on mobile (Dawn)
- [ ] Page looks good on mobile (Horizon)

## 5. Offers & Pricing
- [ ] Volume offer 1/2/3 units: correct prices
- [ ] Savings vs. single-unit price shown correctly
- [ ] Unit price per tier displayed correctly
- [ ] Discount is correct in checkout
- [ ] Offer with end date: timer counts down
- [ ] Timer disappears after expiry
- [ ] Discount stops after expiry
- [ ] Struck-through price does NOT appear without history/attestation

## 6. Compliance
- [ ] Withdrawal link visible in footer (NL)
- [ ] Withdrawal link visible in footer (EN)
- [ ] Withdrawal link visible in footer (DE)
- [ ] Withdrawal form completed without login
- [ ] Confirmation email received with date + time

## 7. Uninstall
- [ ] Uninstall app → confirmation email sent
- [ ] Running jobs cancelled
- [ ] No active charge remains

## 8. Performance
- [ ] Lighthouse mobile ≥ 85 on a generated PDP (Dawn)
- [ ] Lighthouse mobile ≥ 85 on a generated PDP (Horizon)

---

**Release date:** _______________
**Tested by:** _______________
**Result:** PASS / FAIL
