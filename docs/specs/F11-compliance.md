# F11 — EU compliance module

**References:** 07 (complete), 02 (`PriceHistory`, `PriceAttestation`, `GpsrInfo`, `UnitPriceInfo`, `ClaimFinding`), 04 (`mq-price`, `mq-gpsr`, `mq-withdrawal-link`), `prompts/compliance_check.md`.

## Sub-areas and acceptance criteria

### A. Omnibus
1. `prior_price()` and `reduction()` pass for all test cases in 07 §1.4.
2. A `products/update` webhook with a new price adds exactly one `PriceHistory` row; same price → no row.
3. Daily beat task sets/deletes `prior_price` metafields; only set on a real reduction.
4. Attestation only possible within 30 days after installation; hidden afterwards.

### B. Unit price
5. `unit_price()` according to 07 §2.3 for all units and tiers; reference unit always 1 kg / 1 l / 1 m / 1 m² / 1 m³.
6. A variant with `applies = True` without `net_quantity` blocks activation of an offer and setting a page live for that product.

### C. Timers and scarcity
7. Tests from 07 §3 (model, DB constraint, widget behavior with mocked time in a JS test).

### D. Claims
8. Blocklist per language with word boundaries; table 07 §4.1 fully covered by tests (positive and negative example per term).
9. AI check supplements regex; findings not duplicated.

### E. GPSR
10. `GpsrInfo.complete` according to 07 §5; publishing blocked without it.
11. "Kopieer van ander product" ("Copy from another product") copies all fields except `product_identifier`.

### F. AI images
12. See F04 criterion 4; label `ai_image_disclosure` on by default; switching it off is logged.

### G. Legal pages and withdrawal
13. The generator creates pages per language with merchant details and the draft banner until T-090 has been completed.
14. `mq-withdrawal-link` shows the correct label per store language (07 §8.2) on every page and links to `/apps/mosaiq/withdraw`.
15. Onboarding step `withdrawal` shows the checklist from 07 §8.4 with working deep links.
17. `/apps/mosaiq/withdraw` works without login, in two steps, with only the fields name, order reference and email; labels exactly according to 07 §8.2 per store language; the confirm button contains no other text.
18. After confirming: `WithdrawalRequest` with `submitted_at`, confirmation email to the customer within 1 minute with the content of the declaration and date + time, notification to the merchant.
19. Proxy requests with an invalid `signature` → 401; honeypot filled or > 5 submissions per IP per hour → no storage, but a neutral thank-you page.
20. `customers/redact` deletes, and `customers/data_request` exports, the requests of that email address; after 2 years a beat task deletes them.

### H. Score
16. Compliance score according to 07 §9, visible in the editor and page list.

## Assumptions made during build
- **EMPCO_GENERIC NL heuristic (07 §4.1):** "groen" is matched with word boundaries plus an exclusion list (e.g. "groente") instead of POS tagging (BUILD_LOG item 4).
- **C2PA on CDN variants (Q3):** treated as absent; SynthID + visible label carry the marking (see F04).
