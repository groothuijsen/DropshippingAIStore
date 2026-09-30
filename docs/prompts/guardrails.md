# Guardrails per niche (inserted into `copy.md` as `{{ guardrails }}`)

The code selects the block based on `ResearchResult.niche`. The block goes into the prompt verbatim (English).

## wellness_sleep

```
Niche rules (wellness & sleep products, e.g. weighted sleep masks, aromatherapy):
- This is NOT a medical device. Never say it treats, cures, prevents or relieves insomnia, anxiety, stress disorders, pain, migraines or any condition.
- Allowed: comfort, relaxation, calm, a restful evening routine, blocking light, a soft weighted feel.
- Essential oils / scents: no health effects. You may describe the scent and the ritual.
- Include safety wording only if it is in the facts (e.g. "do not use while driving", "keep oils away from eyes").
```

## auto_accessories

```
Niche rules (car accessories):
- Never claim road legality, type approval, E-marking, TÜV/RDW approval unless the facts contain the exact certificate; then quote only the certificate number from the facts.
- For lighting and visibility products without a certificate in the facts, do not mention public-road use.
- Fitment: only list car models present in the facts. Never say "fits all cars".
- Cleaning/care liquids: mention volume from the facts (needed for unit price).
```

## pod_merch

```
Niche rules (print-on-demand apparel and merchandise):
- Never mention or allude to sports teams, racing teams, drivers, clubs, brands, franchises, films, games or their logos, unless the facts state a licence.
- Describe the design in neutral terms (style, colours, theme).
- Fabric composition and care instructions only from the facts; do not invent percentages.
- Sizes: refer to the size chart; never promise "true to size" unless in the facts.
```

## other

```
Niche rules: follow the general rules. Avoid any health, environmental, legal-compliance or performance claim that is not literally supported by the facts.
```
