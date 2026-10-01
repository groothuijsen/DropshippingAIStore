# F05 — BrandKit, style presets and onboarding

**References:** 02 (`BrandKit`, `Shop.onboarding_step`), 03 §5.2 (app-data metafield `design_tokens`), 04 (`mq-tokens`), 09 (onboarding).

## Acceptance criteria

1. Onboarding goes through `language` → `brand` → `sources` → `theme` → `withdrawal` → `done`; the back button works; stopping halfway and returning later resumes at the last step.
2. **Brand step:** merchant enters brand name and tone, chooses one of 6 presets, or lets AI suggest a palette based on product photos (one AI call, does not count as a generation).
3. Palette validation: hex codes valid; contrast `text` on `background` ≥ 4.5:1 (WCAG); otherwise an error message with a suggested correction.
4. Fonts: choice from the 6 bundled fonts (04 `mq-tokens`, list in `themes/fonts.py`) or "Font van mijn thema" ("My theme's font"); stored in `design_tokens.fonts`.
5. **When** the BrandKit is saved, **then** Mosaiq writes `design_tokens` to the app installation metafield and sets `tokens_synced_at`; the embed `mq-tokens` shows the new CSS variables on the storefront.
6. Presets are data (`themes/presets.py`): per preset radius, spacing scale, button style, heading style. Two stores with different presets and palettes look visibly different (manual check with screenshots in the PR).

## Assumptions made during build
- **AI palette handling:** the code re-validates every AI proposal (hex format, WCAG contrast ≥ 4.5:1) and corrects or rejects failures; `font_heading`/`font_body` must be keys from the bundled list in `themes/fonts.py`.
