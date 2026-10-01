# F02 — AI research and angle selection

**References:** 05 §2, §3 (`ResearchResult`), §4.2; `prompts/research.md`; 09 (`/app/jobs/<uuid>/angle/`).

## Acceptance criteria

1. **Given** an `ImportResult`, **when** step `research` runs, **then** the output is valid according to `ResearchResult` with exactly 3 angles, 2–3 personas, 4–8 FAQs, all in the content language of the job.
2. **Given** invalid AI output, **then** exactly one repair attempt follows; if it remains invalid → `AI_SCHEMA_INVALID`.
3. **Given** a successful research without `angle_id`, **then** job status `needs_input` and the merchant sees 3 cards (title, hook, persona); after the choice the job continues from `copy` without running research again.
4. `claim_risks` is stored and passed on to step `copy` and `compliance_check`.
5. No `ResearchResult` field contains numbers or specifications that are not in `ImportResult` (test with evalset fixtures: regex on numbers that do not occur in the input → test fails).
6. Costs and tokens are in `AiCall` and add up in `JobStep.ai_cost_usd`.

## Assumptions made during build
- Implemented as specified; no additional assumptions beyond those recorded in `docs/BUILD_LOG.md`.
