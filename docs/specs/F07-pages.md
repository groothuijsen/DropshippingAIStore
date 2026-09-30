# F07 — Pages: editor, draft, live

**References:** 05 §4.5–4.6, 07 §4 and §9, 09 (page editor), 02 (`Page`, `ClaimFinding`), 03 §5 (`metaobject_upsert`, `page_create`, `page_update`, `product_template_suffix`).

## Acceptance criteria

1. **Given** a successful job, **then** a `Page` exists with status `draft`, per language a metaobject in status `DRAFT`, the metafield `page` on product/page/shop, and for landing/advertorial/listicle/about a Shopify page with `isPublished:false`. `Page.version` is 1.
2. The editor shows every section with editable fields and the same length limits as the schema; saving reruns the deterministic claim check and updates the score.
3. "Herschrijf deze zin" ("Rewrite this sentence") replaces only the field concerned, respects guardrails, does not count as a generation.
4. **Given** open `block` findings, incomplete GPSR or a missing mandatory unit price, **then** "Live zetten" ("Set live") is disabled and the list of missing conditions is visible.
5. **When** set live, **then** all language entries `ACTIVE`, page `isPublished:true`, `Page.status = live`. The live pages limit (counted as live, 08 §1) is checked before the action. A later edit + republishing increments `version`.
6. Republishing an existing page uses the same handles from `Page.metaobject_handles` (upsert, no duplicate).
7. If `Shop.mosaiq_templates_ready`, `templateSuffix = "mosaiq"` is set; otherwise not, and the UI points to the placement deep links.
8. Archiving: metaobject back to `DRAFT`, page unpublished, metafield deleted.

## Assumptions made during build
_(to be filled in by Hermes)_
