# Kickoff prompt v1.1 — continue the build (paste into Hermes)

You are continuing the Mosaiq build in ~/Projects/DropshippingAI. AGENTS.md stays binding (precedence: AGENTS.md > docs/00-decisions.md > feature spec > other docs; docs/12 and docs/13 take precedence for F15–F19).

## 1. Catch up (once)
1. Commit any uncommitted work first, as its own commit with a message that names what it is. Never commit shopifycredentials.md or *.db files (both are in .gitignore).
2. Read: AGENTS.md, README.md, docs/12-v1.1-store-builder.md, docs/13-marketing-site.md, docs/specs/F15–F19, docs/prompts/{niche_names,niche_brand,product_ideas,store_structure,edit_page}.md, everything in docs/marketing/, and the v1.1 and v1.2 sections of docs/sprints.md and docs/open-questions.md.
3. Compare them with the code as it is now. Append to docs/BUILD_LOG.md: every contradiction between the new docs and the existing code or docs (file + section), every MVP ticket that is still open or only partly done, and which open questions (Q8–Q25) block which tickets.
4. STOP and report. Do not start a new ticket until I confirm.

## 2. Order of work after my confirmation
1. Finish any open MVP ticket first (up to and including T-092; T-090 and T-093 wait for the lawyer and the listing).
2. Then v1.1 in sprint order S7 → S10 (T-110 … T-121), F18 and F17 before F15 and F16.
3. Then v1.2 (marketing site) S11 → S12 (T-150 … T-159), and finally T-093 (App Store listing).
Always take the lowest ticket in that order whose dependencies are done. One ticket at a time.

## 3. Per ticket (unchanged loop)
Branch `t-###-slug` → failing tests from the Given/When/Then criteria → implement → Definition of Done from README (make test, coverage, ruff, mypy; manual check on Dawn and Horizon for storefront work) → fill in "Assumptions made during build" in the spec → CHANGELOG line → mark the ticket done in sprints.md → commit `[T-###] short description` → PR with the same title, label `needs-review` for anything touching money, legal text, scopes, storefront output or marketing claims → short report → next ticket.

## 4. Stop and ask me when
- A ticket needs a decision from me: Q22 (logo/visual identity), Q23 (company details), Q24 (email provider), Q25 (German review), or the founding-member discount on the early-access page.
- A new Shopify operation behaves differently from the docs (record the real response as a fixture first; Q18–Q21).
- You would add a scope, external service, paid API or dependency not in the docs.
- A marketing claim cannot be marked `verified` in docs/marketing/claims.md: never publish it, report it.
- The same error persists after 3 attempts, or at the end of each sprint (give a short demo summary).

## 5. Non-negotiables
GraphQL Admin API only. Never write theme files or touch `main-menu`, shop policies, or fields owned by sync apps. Never invent business facts (address, delivery times, shipping costs). No third-party requests from the marketing site. Everything in English (code, comments, commits, PRs, docs); user-facing text via i18n or content files in nl/en/de.

Start with section 1.
