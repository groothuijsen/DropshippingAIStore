# 07 — Compliance as code

The legal rationale is in the plan document (section "Juridische toets EU-features" (Legal review of EU features)). This document converts it into exact rules. All functions live in `apps/compliance/` and are pure (no I/O) where possible, so that they are easy to test.

## 1. Omnibus: prior price and discount percentage

### 1.1 Definitions
- **Announced price reduction**: any display of a struck-through price, a "-X%" badge or a word such as "korting/sale/Rabatt" (discount/sale/discount) for a single product.
- **Reduction start time** (`reduction_start`): the moment at which the current price first applied, i.e. the oldest observation in the most recent uninterrupted run of rows with `price == current_price`.
- **Prior price**: the lowest price that applied in the window `[reduction_start − 30 days, reduction_start)`. The window therefore lies before the promotion, not before today (art. 6a: "vóór de toepassing van de prijsvermindering" (prior to the application of the price reduction)).

### 1.2 Algorithm

```python
def prior_price(shop, variant_gid, current: Decimal, market="primary", now=None) -> PriorPrice | None:
    now = now or timezone.now()
    rows = list(
        PriceHistory.objects.filter(
            shop=shop, variant_gid=variant_gid, market_handle=market, observed_at__lte=now
        ).order_by("observed_at")
    )
    if not rows:
        return None
    # 1. start time of the current price
    i = len(rows) - 1
    while i > 0 and rows[i - 1].price == current:
        i -= 1
    reduction_start = rows[i].observed_at
    window_start = reduction_start - timedelta(days=30)
    before = [r for r in rows if r.observed_at < reduction_start]
    # 2. price that applied at window_start = last observation at or before window_start
    anchor = next((r for r in reversed(before) if r.observed_at <= window_start), None)
    in_window = [r.price for r in before if r.observed_at > window_start]
    candidates = in_window + ([anchor.price] if anchor else [])
    if anchor is None:
        # history does not fully cover the window
        att = PriceAttestation.objects.filter(shop=shop, variant_gid=variant_gid, valid_until__gt=now).first()
        if att is None:
            return None  # insufficient history -> do NOT show a reduction
        candidates.append(att.lowest_price_30d)
    if not candidates:
        return None
    return PriorPrice(amount=min(candidates), currency=rows[-1].currency)


def reduction(current: Decimal, prior: Decimal) -> Reduction | None:
    if current >= prior:
        return None  # not a real reduction -> show nothing
    pct = ((prior - current) / prior * 100).to_integral_value(rounding=ROUND_FLOOR)
    return Reduction(prior=prior, current=current, percent=int(pct))
```

### 1.3 Display rules
- `prior_price()` is `None` → `mq-price` shows only the current price; the theme's `compare_at_price` is not used by Mosaiq. Show the merchant a warning if their theme itself displays a compare-at price (we cannot modify the theme).
- Percentages always come from `reduction()`; rounding **down**.
- The metafield `variant.$app:mosaiq.prior_price` is recalculated daily (beat task 03:00 shop time) and on every `products/update`; it is only set if there is a reduction, otherwise it is removed.
- **Not** applicable to volume/BOGO/gift (linked offers). For those, the §2 display from 04 applies (saving relative to the current unit price per item).

### 1.4 Tests (minimum)
History shorter than 30 days without attestation → `None`; with attestation; price increase just before the promotion (the increase does not count as prior price if the lower price was within the window); promotion already running for 10 days (window lies before the promotion, not before today); daily snapshot rows with the same price; multiple price changes within the window; currency per market; percentage 33.9 → 33; current price ≥ prior price → no reduction.

## 2. Unit price

### 2.1 When required
`UnitPriceInfo.applies = True` if the product is sold by weight, volume, length or area. The merchant confirms this per variant; the AI makes a suggestion based on specs (e.g. "30 ml").

### 2.2 Reference unit

| Stored unit | Reference | Factor to reference |
| --- | --- | --- |
| `g` | `1 kg` | ÷ 1000 |
| `kg` | `1 kg` | × 1 |
| `ml` | `1 l` | ÷ 1000 |
| `l` | `1 l` | × 1 |
| `cm` | `1 m` | ÷ 100 |
| `m` | `1 m` | × 1 |
| `m2` | `1 m²` | × 1 |
| `m3` | `1 m³` | × 1 |

No "per 100 g" or "per 100 ml" (no longer permitted in DE). Use the same reference for all countries; that is permitted everywhere.

### 2.3 Calculation

```python
def unit_price(total: Decimal, qty: int, net_quantity: Decimal, unit: str) -> Decimal:
    ref_qty = net_quantity * qty * FACTOR[unit]  # in reference units
    return (total / ref_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- Recalculate per bundle tier using the tier total.
- Display: "€ 83,17 / 1 l" directly below or next to the (tier) price, in a smaller font, never bolder or larger than the price.
- `applies = True` but `net_quantity` missing → publishing an offer with price display is blocked.

## 3. Timers, scarcity and social proof

| Element | Condition for showing | Otherwise |
| --- | --- | --- |
| Countdown timer | `Offer.ends_at` filled in, in the future, `show_timer = True` | do not render |
| After expiry | timer disappears; the Function stops automatically via the discount's `endsAt` | never restart |
| "Only X left in stock" ("Nog X op voorraad") | variant tracks inventory (`variant.inventory_management == 'shopify'`), `0 < variant.inventory_quantity ≤ Shop.stock_threshold` (default 5, max. 10); rendered in `mq-price` (Liquid, no API scope needed) | do not render |
| Delivery time/cut-off ("order before 16:00…" / "vóór 16:00 besteld…") | merchant fills in cut-off and delivery time; only show on working days before the cut-off | do not render |
| "X people are viewing this" / "Y just bought" | **does not exist in Mosaiq** | — |
| Reviews/stars | only via a real review app (e.g. the merchant's Judge.me block); Mosaiq generates nothing | — |

Model validation: `Offer.clean()` rejects `show_timer=True` without `ends_at`, and an `ends_at` more than 90 days in the future (prevents fake "ending soon"). For the DB CheckConstraint see 02.

## 4. Claims (EmpCo, medical, niche)

### 4.1 Deterministic blocklist (`apps/compliance/claims.py`)
Case-insensitive, on word boundaries, per language. Match → `Finding` with the listed `rule_id`.

| rule_id | severity | nl | en | de |
| --- | --- | --- | --- | --- |
| `EMPCO_GENERIC` | block | duurzaam, milieuvriendelijk, groen (als bijvoeglijk nw. bij product), eco, ecologisch, klimaatneutraal, CO2-neutraal, natuurvriendelijk, planeetvriendelijk | sustainable, eco-friendly, eco, green, environmentally friendly, climate neutral, carbon neutral, planet-friendly, nature-friendly | nachhaltig, umweltfreundlich, öko, grün, klimaneutral, CO2-neutral, naturfreundlich |
| `MED_CLAIM` | block | geneest, behandelt, verhelpt, tegen slapeloosheid, tegen angst, pijnverlichting, klinisch bewezen, medisch getest | cures, treats, heals, relieves insomnia, anti-anxiety, pain relief, clinically proven, medically tested | heilt, behandelt, lindert Schlaflosigkeit, gegen Angst, Schmerzlinderung, klinisch bewiesen, medizinisch getestet |
| `FAKE_URGENCY` | block | alleen vandaag, bijna uitverkocht, laatste kans, op=op | only today, almost sold out, last chance, while stocks last | nur heute, fast ausverkauft, letzte Chance, solange der Vorrat reicht |
| `FAKE_SOCIAL` | block | bestseller, x tevreden klanten, bekend van | bestseller, happy customers, as seen on | Bestseller, zufriedene Kunden, bekannt aus |
| `SUPERLATIVE` | warn | de beste, nummer 1, perfect, gegarandeerd resultaat | the best, #1, perfect, guaranteed results | der/die/das beste, Nr. 1, perfekt, garantiert |
| `AUTO_ROADLEGAL` | block (niche auto) | straatlegaal, E-keur, RDW-goedgekeurd, toegestaan op de openbare weg | road legal, E-approved, street legal | straßenzugelassen, E-Prüfzeichen, TÜV-geprüft, StVZO-konform |

Note on the `nl` column of `EMPCO_GENERIC`: "groen (als bijvoeglijk nw. bij product)" means "groen" only when used as an adjective describing the product.

Rules that **only** the AI check finds (no fixed word list): `EMPCO_LABEL` (block: self-invented quality marks/badges), `UNSUPPORTED_FACT` (warn: number or specification not in the facts), `IP_REFERENCE` (block, niche POD: names/logos of teams, brands, drivers, franchises). Together with the table above, this is the complete list of valid `rule_id`s; the code rejects any other value.

Exception for `EMPCO_GENERIC` (generic environmental claim): the match becomes `warn` instead of `block` if the same sentence contains a specific, verifiable fact from `ImportResult.facts` (e.g. "100% recycled polyester"). The AI check (prompt `compliance_check.md`) assesses whether that fact actually substantiates the claim.

### 4.2 Handling in the UI
- `block`: text highlighted, button "Rewrite this sentence" ("Herschrijf deze zin"; AI with the suggestion) or manual editing. Publishing disabled until resolved.
- `warn`: publishing is allowed after filling in `override_reason` (logged in `AuditLog`).

## 5. GPSR (art. 19)

- `GpsrInfo.complete = True` if: `manufacturer_name`, `manufacturer_address`, `manufacturer_email` are filled in; if `manufacturer_in_eu = False`, all `eu_rp_*` fields as well; `product_identifier` filled in; `warnings` filled in for the content language **or** `no_warnings_confirmed = True`.
- `publish` (05 §4.6) refuses without `complete`.
- Metafield `product.$app:mosaiq.gpsr` contains the fields; block `mq-gpsr` displays them in the store language.
- Onboarding help: for dropshipping from outside the EU, the explanation "you need an EU responsible person (e.g. an importer or a service)" ("je hebt een EU-verantwoordelijke nodig (bijv. een importeur of dienst)").

## 6. AI images (AI Act art. 50)

- Only providers from 00-decisions. Both deliver an invisible SynthID watermark and a C2PA manifest ([Gemini docs](https://ai.google.dev/gemini-api/docs/image-generation), [Google Cloud blog](https://cloud.google.com/blog/products/ai-machine-learning/bringing-nano-banana-2-to-enterprise), [OpenAI](https://help.openai.com/en/articles/8912793)).
- Own C2PA manifest on every published AI image, with the provider manifest preserved as a `parentOf` ingredient (05 §4.4). If signing fails → do not publish the image, log the error.
- **CDN:** there is no source stating whether Shopify preserves C2PA metadata when converting to WebP/AVIF or resizing; other CDNs often strip it (Cloudflare only preserves it with a separate setting). Therefore assume: the original in Shopify Files possibly with manifest, transformed variants without. The marking then relies on (1) SynthID in the pixels, which survives resizing and conversion, and (2) the visible label. T-043 confirms this with `c2patool` and `exiftool` on the original and on `?width=800&format=webp` variants via `scripts/verify_c2pa.py`.
- **T-043 verification procedure** (run against the dev store once uploads are live):
  1. Install tools: `brew install c2pa exiftool` (or `pip install c2pa-cli`).
  2. Upload a signed AI image via the pipeline (T-042 flow).
  3. Run `python scripts/verify_c2pa.py <files_url>` for the original.
  4. Run `python scripts/verify_c2pa.py <files_url> --variant "width=800&format=webp"` for the CDN variant.
  5. Record results below; update this section with confirmed findings.
- **Q3 findings (pending dev-store verification):** assumption stands — original may have manifest, CDN variants may not. SynthID + visible label are the reliable markers.
- `ai_image_disclosure` in the metaobject defaults to `true`; the block shows a small label "Image created with AI" ("Afbeelding gemaakt met AI") (per language). The merchant can turn it off; this is logged.
- No recognizable real people (prompt rule + `people_allowed = false`).
- The visible label is therefore **on** by default; turning it off shows the merchant a warning.

## 7. Legal pages

- The generator (`compliance.legal.generate(shop, locale)`) creates/updates via `page_create`/`page_update` (not via Shopify policies, which remain the merchant's):
  - right of withdrawal (14 days, from delivery of the last item) + model form;
  - impressum (only for market DE, mandatory for German customers);
  - GPSR/contact page with manufacturer details per product (linked from `mq-gpsr`).
- Texts are templates in `apps/compliance/legal_templates/<lang>/` with merchant details filled in; **approved by the lawyer before launch** (ticket T-090). Until then, the top of the page shows: "Concept — laat controleren" ("Draft — have this reviewed").

## 8. Withdrawal function (since 19 June 2026)

Legal basis: art. 11a Consumer Rights Directive (inserted by Directive 2023/2673). NL: art. 6:230oa BW (Stb. 2026, 153, in force ±25 June 2026). DE: § 356a BGB (BGBl. 2026 I Nr. 28, in force 19 June 2026). BE: transposition unclear (sources contradict each other) → follow the directive text and have the lawyer confirm.

### 8.1 Why a custom guest form in the MVP
Shopify does not offer a separate withdrawal button; the route via customer accounts requires logging in. In Germany, according to the prevailing interpretation (Bitkom, ITMR), requiring login is in principle not permitted, unless the contract could only be concluded via a customer account. In the Netherlands, logging in for identification is permitted, but mandatory account creation is not (Thuiswinkel.org). Because DE is a core market, the guest form is **in the MVP** (T-088), not in v1.1.

An app **cannot** read or set return and cancellation settings via the Admin API (confirmed by Shopify staff on community.shopify.dev, 2025; nothing changed in 2026). The onboarding checklist with deep links therefore remains necessary.

### 8.2 Labels (per store language)

| Language | Link / button step 1 | Button step 2 (confirm) | Explanation |
| --- | --- | --- | --- |
| `nl` | Hier de overeenkomst ontbinden | Ontbinding bevestigen | The BW does not prescribe fixed wording ("ondubbelzinnige formulering" (unambiguous wording)); this follows the term "ontbinden" (to dissolve/terminate) from art. 6:230oa and the advice of Thuiswinkel.org. Alternative from the directive: "hier de overeenkomst herroepen" / "herroeping bevestigen" (withdraw from the contract here / confirm withdrawal). |
| `de` | Vertrag widerrufen | Widerruf bestätigen | Literally the statutory text; Bitkom advises against deviating from it (Abmahnrisiko (risk of a cease-and-desist warning)). |
| `en` | Withdraw from contract here | Confirm withdrawal | Literally the directive text. |

- The confirmation button carries **only** these words (directive: "only with the words … or …"); no additional text on the button.
- The merchant cannot modify the labels in the MVP (prevents errors).

### 8.3 Flow (app proxy `/apps/mosaiq/withdraw`, see 03 §1)
1. **Step 1 – form**, only these fields: name, order number or other identification of the contract, email address for the confirmation. No mandatory reason, no login, no captcha that blocks without JavaScript (honeypot field + rate limit per IP in Redis: max. 5 per hour).
2. **Step 2 – review and confirm**: shows the entered data and the button from §8.2.
3. After confirmation: store `WithdrawalRequest` (02) with `submitted_at`; **immediately** send a confirmation email to the customer with the content of the statement and the date + time of submission (durable medium), and a notification to the merchant (email + list in Mosaiq under Settings → Withdrawals).
4. The form does **not** validate the order number against Shopify (no `read_orders`, no additional customer data); the merchant assesses the request themselves. A statement submitted in time counts, even if processing follows later.
5. Page and emails in the store's language (`request.locale` via the proxy parameters, otherwise the primary language).

### 8.4 Onboarding checklist (remains)
Self-service returns and cancellations on, cancellation "Until item is fulfilled", return window ≥ 14 days from "Delivery of last item in order", extend for weekends/public holidays — with deep links to Settings → Policies. Mosaiq cannot verify this; the merchant ticks it off.

## 9. Compliance score per page

`Page.compliance_score = 100 − 25 × open_block_count − 5 × open_warn_count (without override) − 20 if GPSR incomplete − 10 if unit price missing where required`, minimum 0. Recalculated on every change to sections, findings, GPSR or unit price. (`ComplianceReport.claims_score` in 05 counts only the claims.) Shown in the editor and the page list. Publishing requires: no open `block`, GPSR complete, unit price complete where required.

## v1.1 additions

See `docs/12-v1.1-store-builder.md` §8 (delivery information, 30-day rule, SHIPPING_CLAIM, brand-name rules, price advisor and Omnibus). That document takes precedence for F15–F18.
