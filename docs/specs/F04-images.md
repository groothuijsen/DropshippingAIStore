# F04 — AI product images

**References:** 05 §4.4, `prompts/images.md`, 07 §6, 08 §1 (limit `ai_images`), 03 §5 (`staged_uploads_create`, `file_create`), open questions Q2, Q3.

## Acceptance criteria

1. **Given** at least 1 own product photo and remaining credits, **when** step `images` runs, **then** at most `min(5, credits)` images are created for the slots that the sections use.
2. Provider Vertex fails (provider error) → the same shot via OpenAI; both fail → skip slot, job continues.
3. Every image goes through the fidelity check (`FidelityResult`); rejected after 2 attempts → not uploaded, slot in `ImageResult.rejected_slots`, message `IMAGE_FIDELITY_REJECTED` (warning, not a job error).
4. Every published image has its own C2PA manifest (checked in test with the `c2pa-python` reader on the file before upload). Signing fails → do not publish.
5. Upload via staged upload + `fileCreate`; the task waits until `READY` (max. 60 s); timeout → skip slot with error log.
6. Alt text in content language, ≤ 125 characters.
7. Counter `ai_images` increases only by the number of successfully uploaded images.
8. Images are **not** added to the product gallery on locked products; they are stored in `Page.images` and in the metaobject fields `image_<slot>` (03 §5.1).
9. T-043 records whether C2PA is preserved after CDN rendering (Q3) and updates 07 §6.

## Assumptions made during build
- **Slot→resolution mapping (05 §4.4):** 2K for `hero` and `lifestyle_*` slots, 1K for `detail_*` (BUILD_LOG item 3).
- **Metaobject file references (03 §5.1):** the `File` GID returned by `fileCreate` is written directly as `file_reference` in `metaobjectUpsert`; shape verified with a recorded fixture (BUILD_LOG item 8).
- **Q3 (C2PA on CDN variants):** assumption stands — the original in Files may carry the manifest, `?width=…&format=webp` variants may not. SynthID in the pixels plus the visible AI label are the reliable markers; procedure documented in 07 §6 with `scripts/verify_c2pa.py`.
