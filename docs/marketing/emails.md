# Email copy

All emails: plain, short, from "Paul at Mosaiq", reply-to the support address, unsubscribe link in every non-transactional email, sent in the recipient's `locale` (nl/en/de; DE from T-158). Sender domain authenticated (SPF, DKIM, DMARC) on `mosaiq.marketing`.

## 1. Early-access confirmation (transactional, double opt-in)
**EN** — Subject: Confirm your spot on the Mosaiq early-access list
Hi, please confirm your email address so we can keep you posted about early access: {confirm_link}. The link works for 7 days. Didn't sign up? Ignore this email and we won't contact you again. — Paul, Mosaiq
**NL** — Onderwerp: Bevestig je plek op de early-accesslijst van Mosaiq
Hoi, bevestig je e-mailadres zodat we je op de hoogte kunnen houden over vroege toegang: {confirm_link}. De link werkt 7 dagen. Heb je je niet aangemeld? Negeer deze mail, dan hoor je niets meer van ons. — Paul, Mosaiq

## 2. Launch announcement (marketing, only to confirmed leads)
**EN** — Subject: Mosaiq is live on the Shopify App Store
Mosaiq is now on the Shopify App Store. Install it here: {listing_url}. {founding_member_line} Questions? Just reply. — Paul
**NL** — Onderwerp: Mosaiq staat live in de Shopify App Store
Mosaiq staat nu in de Shopify App Store. Installeren kan hier: {listing_url}. {founding_member_line} Vragen? Reageer gewoon op deze mail. — Paul
`{founding_member_line}` only if the founding-member discount exists (see site copy note).

## 3. In-app onboarding sequence (after install; stops on uninstall or unsubscribe)
| Day | Condition | EN subject | NL subject | Content (one action per email) |
| --- | --- | --- | --- | --- |
| 0 | install | Welcome — your first page in a few minutes [C-03] | Welkom — je eerste pagina in een paar minuten | Link to onboarding; 3 steps; link to `/help/installation/` |
| 1 | no page generated | Pick one product and try it | Kies één product en probeer het | Deep link to Generate |
| 3 | page generated, not live | What's blocking your page from going live | Wat je pagina nog tegenhoudt | Explain the compliance panel; link to the page |
| 5 | blocks not placed (no "Done" in onboarding theme step) | Two clicks to show Mosaiq in your theme | Twee klikken om Mosaiq in je thema te tonen | Deep links + help article |
| 5 | trial ends in 48 h | existing trial reminder (F12, T-062) — not duplicated here | | |
| 10 | live page, no offer | Add a bundle to that page | Voeg een bundel toe aan die pagina | Link to Offers |
| 30 | active, ≥ 1 live page | How is it going? | Hoe gaat het? | Ask for feedback and (only then) a review link; never incentivise reviews |
Day 3 uses `[C-03]` only once verified; until then "Welcome — let's build your first page".

## 4. Cancellation / uninstall
Existing (F13). Add one optional question link: "What made you leave?" (one-click reasons, no follow-up sales email).
