# Legal pages — outline for drafting and lawyer review

Drafts are written from this outline, published with the draft banner, and finalised by the lawyer (T-090, extended by T-156). Placeholders in `{}` come from settings (Q23). This outline is not legal advice.

## Privacy policy (`/legal/privacy/`) — Mosaiq as controller (site visitors, leads, merchants as customers)
1. Who we are: {legal_name}, {address}, {company_reg_no}, {vat_id}, contact email.
2. What we collect and why, with legal basis per purpose (GDPR art. 6): site analytics (cookieless, legitimate interest); early-access and newsletter leads (consent); merchant account and billing data (contract); support messages (contract / legitimate interest); app usage and AI-generation logs (contract, legitimate interest for security and abuse prevention).
3. Retention per category, including: unconfirmed leads 30 days; `TrialLedger` hashed shop domains kept to prevent trial abuse (08); support tickets {period}; logs {period}.
4. Recipients and sub-processors: link to `/legal/subprocessors/`. International transfers and safeguards (EU–US Data Privacy Framework or SCCs per provider).
5. Rights: access, rectification, erasure, restriction, portability, objection, withdrawal of consent; complaint to the Autoriteit Persoonsgegevens.
6. No automated decision-making with legal effects.
7. Changes and version date.

## Data processing agreement (`/legal/dpa/`) — Mosaiq as processor for merchants
Covers shopper data Mosaiq processes on the merchant's behalf: withdrawal requests (`WithdrawalRequest`, 07 §8) and GDPR webhook handling. Standard clauses per GDPR art. 28: subject matter, duration, nature and purpose, data categories, instructions, confidentiality, security measures (encryption at rest for tokens, EU hosting, access control, backups), sub-processors and notification of changes, assistance with data-subject requests, breach notification within {hours}, deletion at end (via `shop/redact`), audits.

## Sub-processors (`/legal/subprocessors/`)
| Provider | Purpose | Data | Location / transfer basis |
| --- | --- | --- | --- |
| Shopify | App platform, billing | merchant and store data | per Shopify terms |
| Hosting provider of the Proxmox server ({provider}) | hosting, backups | all app data | {country} (Q: C-22) |
| Anthropic | AI text generation and checks | product data, prompts (no shopper data) | US — DPF/SCCs |
| Google Cloud (Vertex AI, location EU) | AI image generation | product images and prompts | EU endpoint (Q12b) |
| OpenAI | fallback image generation | product images and prompts | US — DPF/SCCs (Q15) |
| Email provider ({provider}) | transactional and marketing email | email addresses, message content | {country} (Q24) |
| GlitchTip (self-hosted) | error tracking | technical logs | own server |

## Terms of service (`/legal/terms/`) — B2B
Parties and acceptance via install; the service and plan limits (link to pricing); billing via Shopify, trial, cancellation; acceptable use (no prohibited products, no fake reviews or deceptive practices, merchant responsible for products and legal compliance); AI output: merchant reviews before publishing, no guarantee of legal compliance or results; intellectual property and licence to generated content; availability (no SLA on starter/pro) and storefront independence; liability cap {amount or 12 months' fees}; termination; Dutch law, court of {city}; changes with notice.

## Cookie statement (`/legal/cookies/`)
Only the strictly necessary CSRF cookie on pages with a form; analytics without cookies; no third-party cookies; therefore no consent banner.

## Company details (`/legal/company/`) and footer
{legal_name} · {address} · KvK {company_reg_no} · VAT {vat_id} · {email}. (Dutch Commercial Register Act: KvK number on the website.)

## Affiliate terms (summary page under `/affiliates/`)
Commission 30% recurring for 12 months, payment threshold and schedule, prohibited promotion (fake urgency, income claims, brand bidding, spam), termination, tax responsibility of the affiliate.
