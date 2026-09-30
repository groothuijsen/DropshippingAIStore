# 10 — Testing

## 1. Setup

- `pytest` with `pytest-django`, settings `config.settings.test` (Postgres in Docker, not SQLite: JSONField behavior and constraints must be identical to production).
- Celery in tests: `CELERY_TASK_ALWAYS_EAGER = True` and `CELERY_TASK_EAGER_PROPAGATES = True`.
- Network forbidden in tests: `pytest-socket` with `--disable-socket`; all HTTP via `respx` mocks.
- Time: `freezegun` for everything involving 30 days, trials and timers.
- Factories (`factory_boy`) per model in `tests/factories.py`.

## 2. Fixtures

| Folder | Contents | Source |
| --- | --- | --- |
| `tests/fixtures/shopify/` | GraphQL responses per operation, incl. `userErrors` and `THROTTLED` variants | recorded with `scripts/gql.py`; error variants manually derived from a real response |
| `tests/fixtures/shopify/webhooks/` | payloads per topic + correct HMAC headers | Shopify CLI `shopify app webhook trigger` and recorded |
| `tests/fixtures/ai/` | AI responses per step (valid, invalid schema, repaired version) | recorded from real calls in dev |
| `extensions/bundle-discount/tests/` | Function input/output per case (04 §2) | manual, validated with `shopify app function run` |

## 3. Required test groups

1. **Auth:** valid/expired/forged session token; wrong `aud`; `dest` ≠ shop; token exchange success and failure.
2. **Webhooks:** HMAC correct/incorrect; duplicate webhook ID; every topic from 03 §3; `shop/redact` deletes all rows of the shop but not `TrialLedger`.
3. **Ownership (06):** every function that mutates a product, called on a locked product → `LockedFieldError`, and no HTTP call goes out.
4. **Compliance (07):** all cases from 07 §1.4; unit price per unit and tier; timer without `ends_at` impossible (model + DB); blocklist per language incl. word boundaries ("groente" does not match on "groen").
5. **Pipeline (05):** restart skips succeeded steps; schema repair; budget stop; failed job does not increment counters; `needs_input` flow.
6. **Billing (08):** trial ledger; limit race with two parallel jobs; upgrade/downgrade.
7. **Throttling:** client waits based on `throttleStatus`; `THROTTLED` retry sequence.
8. **Tokens:** refresh < 5 min before expiry; concurrent refresh with two threads → one refresh call (Redis lock); failed refresh → `needs_reauth`.
9. **Withdrawal:** proxy signature correct/incorrect; two steps; labels per language exact; confirmation email with date + time; rate limit; redact/data_request.

## 4. AI evalset (`tests/evalset/`, `make eval`)

- 30 products as JSON (`ImportResult` shape): 10 wellness/sleep, 10 car accessories, 10 POD merch, spread across NL/EN/DE.
- Runs real AI calls (not in CI; manually or weekly), writes `eval-report-<date>.md`.
- Measures per product: schema valid (yes/no), number of compliance `block` findings (target 0), fabricated specs (compare `specs.rows` with input; target 0), length overruns (target 0), cost, duration.
- A prompt change may only be merged if the evalset does not score worse than the previous run (SOP-6).

## 5. Manual checklist per release (dev store, Dawn and Horizon)

- [ ] Install → onboarding → choose plan (test mode) → trial active
- [ ] Import product with DSers and with Printify (test product), source shown correctly, fields locked
- [ ] Generate PDP in NL, choose angle, editor, resolve compliance block, fill in GPSR, publish draft, set live
- [ ] Add blocks via deep links; page looks good on mobile
- [ ] Volume offer 1/2/3 units: correct prices, savings vs. single-unit price, unit price per tier; discount is correct in checkout
- [ ] Offer with end date: timer counts down, disappears after expiry, discount stops
- [ ] Struck-through price does not appear without history/attestation
- [ ] Withdrawal link visible in footer in NL/EN/DE; form completed without login; confirmation email received
- [ ] Uninstall → confirmation email, jobs cancelled, no active charge
- [ ] Lighthouse mobile ≥ 85 on a generated PDP
