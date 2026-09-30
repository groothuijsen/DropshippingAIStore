# F14 — In-app support

**References:** 09 (`/app/support/`), plan document SOP-4.

## Acceptance criteria

1. On every screen there is a "Hulp" ("Help") button at the top right linking to `/app/support/`.
2. The support page shows: contact form (subject, message, optional screenshot upload ≤ 5 MB), email address, link to the status page, 10 FAQs in NL/EN/DE.
3. The form sends an email to the support inbox with shop domain, plan, last 5 job IDs and error codes (no tokens, no shopper data) and shows the merchant a confirmation with the expected response time.
4. Billing-related subjects get the label `[BILLING]` in the subject line (priority, SOP-4).
5. AI chat in the app is **not** in MVP (v1.1); the FAQ and the form are sufficient.

## Assumptions made during build
_(to be filled in by Hermes)_
