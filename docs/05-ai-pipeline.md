# 05 — AI pipeline

## 1. Overview

A single `GenerationJob` runs through a fixed sequence of steps. Each step is a Celery task that stores its output as a checkpoint in `JobStep.output`. On restart, steps with status `succeeded` are skipped.

| # | Step (`StepName`) | Queue | Soft/hard time limit | Output schema |
| --- | --- | --- | --- | --- |
| 1 | `import` | `shopify` | 60 / 90 s | `ImportResult` |
| 2 | `research` | `ai` | 120 / 180 s | `ResearchResult` |
| 3 | `copy` | `ai` | 180 / 240 s | `SectionsPayload` |
| 4 | `images` | `ai` | 240 / 300 s | `ImageResult` |
| 5 | `compliance_check` | `ai` | 60 / 90 s | `ComplianceReport` |
| 6 | `layout` | `default` | 30 / 60 s | `LayoutResult` |
| 7 | `publish` | `shopify` | 120 / 180 s | `PublishResult` (writes to Shopify as a **draft**) |

Orchestration: `generator.tasks.run_job(job_id)` builds a Celery `chain` of the steps that are not yet `succeeded`. Going live is a separate action by the merchant (`generator.tasks.go_live(page_id)`), not a pipeline step.

For `kind = store`: the store job itself runs only `import` and `research`. After that (once the angle has been chosen) it creates three child jobs (`parent` = store job) with `page_type` `home`, `pdp` and `about`, each of which runs its own steps starting from `copy` and reuses the parent's `ImportResult`/`ResearchResult` (copied as a `succeeded` checkpoint). The store job is `succeeded` when all three child jobs are `succeeded`; it counts as **one** store generation.

Order of the steps per job: `import` → `research` → `copy` → **create `Page`** (status `draft`, local only) → `images` → `compliance_check` → `layout` → `publish` (draft in Shopify).

**Resuming after `needs_input`:**
- after `research` (choose angle): `run_job` again; starts at `copy`.
- after `compliance_check` with `block`: the merchant edits the text in the editor and clicks "Re-check" ("Opnieuw controleren"). This resets step `compliance_check` to `pending` (and `layout`/`publish` as well) and calls `run_job`. The steps `copy` and `images` are not re-run; `layout` always reads `Page.sections` (the edited version), not the original `copy` output.
- after `import` with a URL (§4.1): the merchant confirms the prefilled form; the product is created manually and the job restarts from `import`.

## 2. Rules for every AI call

1. Prompt from `docs/prompts/<stap>.md` (one prompt per step; the target language is a variable), rendered with Django templating (`{{ }}`), never with f-strings.
2. Anthropic: tool use with a single tool `submit_<stap>` whose `input_schema = Model.model_json_schema()`; `tool_choice = {"type": "tool", "name": "submit_<stap>"}`.
3. Validate the tool input with `Model.model_validate()`.
4. Validation fails → **one** repair attempt: send back the original output + `ValidationError.errors()` with the instruction "correct only these fields". If that also fails → step `failed` with `AI_SCHEMA_INVALID`.
5. Provider error (HTTP 429/500/502/503/529, timeout): retry after 10 s and 30 s. After that, `AI_PROVIDER_ERROR`.
6. Add up the costs after every call. If the job exceeds **USD 2.00** → stop with `AI_BUDGET_EXCEEDED`. Average per store > `AI_COST_ALERT_USD_PER_STORE` over 24 h → alert (11-ops).
7. Never put shoppers' personal data in a prompt.
8. Variable `country_hint`: `Shop.country_code` if it is `NL`, `BE` or `DE`; otherwise derived from the content language (`nl`→`NL`, `de`→`DE`, `en`→`the UK and international buyers`). `locale_name`: `Dutch`, `English` or `German`.

## 3. Schemas (Pydantic v2, `apps/ai/schemas.py`)

```python
from decimal import Decimal
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, HttpUrl, model_validator

Locale = Literal["nl", "en", "de"]
Niche = Literal["wellness_sleep", "auto_accessories", "pod_merch", "other"]


# ---------- input ----------
class ManualProduct(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=20, max_length=5000)
    specs: dict[str, str] = Field(default_factory=dict, max_length=30)
    price: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class JobInput(BaseModel):
    kind: Literal["store", "page"]
    saved_template_id: str | None = None  # F08; only when kind="page"
    product_gid: str | None = None  # existing Shopify product (preferred)
    manual: ManualProduct | None = None  # new manual product
    source_url: HttpUrl | None = None  # extract facts only, never copy images/text
    page_type: Literal["pdp", "landing", "advertorial", "listicle", "home", "about"] | None = (
        None  # required when kind="page"
    )
    content_locale: Locale
    niche_hint: Niche | None = None
    angle_id: str | None = None  # chosen angle from an earlier research
    style_preset: Literal["clean", "bold", "organic", "luxe", "tech", "soft"]

    @model_validator(mode="after")
    def exactly_one_source(self):
        given = [x is not None for x in (self.product_gid, self.manual, self.source_url)]
        if sum(given) != 1:
            raise ValueError("exactly one of product_gid, manual or source_url is required")
        return self


# ---------- step 1 ----------
class ImportResult(BaseModel):
    product_gid: str | None
    source_app: Literal["manual", "dsers", "cj", "zendrop", "autods", "printify", "unknown_app"]
    title: str
    facts: list[str] = Field(max_length=40)  # factual characteristics, in own words
    specs: dict[str, str]
    reference_image_urls: list[str] = Field(max_length=8)  # only the merchant's own Shopify media
    price: Decimal | None
    currency: str | None
    locked_fields: list[str]


# ---------- step 2 ----------
class Persona(BaseModel):
    id: Annotated[str, Field(pattern=r"^p[1-3]$")]
    name: str = Field(max_length=40)
    description: str = Field(max_length=300)
    pains: list[str] = Field(min_length=2, max_length=5)
    desires: list[str] = Field(min_length=2, max_length=5)


class Angle(BaseModel):
    id: Annotated[str, Field(pattern=r"^a[1-3]$")]
    title: str = Field(max_length=80)
    hook: str = Field(max_length=160)
    persona_id: str


class FaqItem(BaseModel):
    q: str = Field(max_length=140)
    a: str = Field(max_length=600)


class ResearchResult(BaseModel):
    niche: Niche
    product_summary: str = Field(max_length=500)
    personas: list[Persona] = Field(min_length=2, max_length=3)
    angles: list[Angle] = Field(min_length=3, max_length=3)
    usps: list[str] = Field(min_length=3, max_length=6)
    objections: list[str] = Field(min_length=2, max_length=6)
    faq: list[FaqItem] = Field(min_length=4, max_length=8)
    claim_risks: list[str] = Field(max_length=10)  # which claims we may NOT make


# ---------- step 3: sections ----------
class Hero(BaseModel):
    type: Literal["hero"] = "hero"
    headline: str = Field(max_length=70)
    subheadline: str = Field(max_length=160)
    cta_label: str = Field(max_length=30)
    image_slot: Literal["hero"] = "hero"


class BenefitItem(BaseModel):
    title: str = Field(max_length=50)
    text: str = Field(max_length=200)
    icon: Literal["check", "moon", "leaf", "shield", "clock", "heart", "star", "truck", "sparkle", "car", "shirt"]


class Benefits(BaseModel):
    type: Literal["benefits"] = "benefits"
    title: str = Field(max_length=70)
    items: list[BenefitItem] = Field(min_length=3, max_length=6)


class ProblemSolution(BaseModel):
    type: Literal["problem_solution"] = "problem_solution"
    problem: str = Field(max_length=400)
    solution: str = Field(max_length=400)
    image_slot: Literal["lifestyle_1"] = "lifestyle_1"


class Step(BaseModel):
    title: str = Field(max_length=50)
    text: str = Field(max_length=200)


class HowItWorks(BaseModel):
    type: Literal["how_it_works"] = "how_it_works"
    steps: list[Step] = Field(min_length=2, max_length=5)


class SpecRow(BaseModel):
    label: str = Field(max_length=60)  # key from ImportResult.specs
    value: str = Field(max_length=120)


class Specs(BaseModel):
    type: Literal["specs"] = "specs"
    rows: list[SpecRow] = Field(min_length=2, max_length=20)  # only from ImportResult.specs


class ComparisonRow(BaseModel):
    feature: str = Field(max_length=80)
    ours: bool
    other: bool


class Comparison(BaseModel):
    type: Literal["comparison"] = "comparison"
    ours_label: str = Field(max_length=30)
    other_label: str = Field(max_length=30)  # generic ("ordinary solution"), never a brand name
    rows: list[ComparisonRow] = Field(min_length=3, max_length=8)


class Faq(BaseModel):
    type: Literal["faq"] = "faq"
    items: list[FaqItem] = Field(min_length=4, max_length=8)


class Guarantee(BaseModel):
    type: Literal["guarantee"] = "guarantee"
    text: str = Field(max_length=300)  # only the merchant's actual policy


class RichText(BaseModel):
    type: Literal["rich_text"] = "rich_text"  # advertorial body
    title: str | None = Field(default=None, max_length=90)
    paragraphs: list[str] = Field(min_length=1, max_length=12)
    image_slot: Literal["lifestyle_1", "lifestyle_2", "detail_1", None] = None


class ListicleItem(BaseModel):
    type: Literal["listicle_item"] = "listicle_item"
    number: int = Field(ge=1, le=10)
    title: str = Field(max_length=90)
    text: str = Field(max_length=600)
    image_slot: Literal["lifestyle_1", "lifestyle_2", "detail_1", "detail_2", None] = None


class Cta(BaseModel):
    type: Literal["cta"] = "cta"
    headline: str = Field(max_length=70)
    button_label: str = Field(max_length=30)


Section = Annotated[
    Union[Hero, Benefits, ProblemSolution, HowItWorks, Specs, Comparison, Faq, Guarantee, RichText, ListicleItem, Cta],
    Field(discriminator="type"),
]


class SectionsPayload(BaseModel):
    locale: Locale
    page_type: Literal["pdp", "landing", "advertorial", "listicle", "home", "about"]
    seo_title: str = Field(max_length=60)
    seo_description: str = Field(max_length=155)
    sections: list[Section] = Field(min_length=2, max_length=14)


# ---------- step 4 ----------
ImageSlot = Literal["hero", "lifestyle_1", "lifestyle_2", "detail_1", "detail_2"]


class ImageShot(BaseModel):
    slot: ImageSlot
    purpose: str = Field(max_length=120)
    prompt: str = Field(max_length=1200)
    aspect_ratio: Literal["1:1", "4:5", "16:9"]
    reference_image_urls: list[str] = Field(min_length=1, max_length=4)
    people_allowed: bool = False  # never recognizable real people


class ImagePlan(BaseModel):  # tool submit_image_plan
    shots: list[ImageShot] = Field(min_length=0, max_length=5)


class FidelityResult(BaseModel):  # tool submit_fidelity
    same_product: bool
    issues: list[str] = Field(max_length=10)


class ImageOut(BaseModel):  # only uploaded, approved images
    slot: ImageSlot
    file_gid: str
    provider: Literal["vertex", "openai"]
    c2pa_signed: Literal[True]
    alt: str = Field(max_length=125)


class ImageResult(BaseModel):
    images: list[ImageOut] = Field(max_length=5)
    rejected_slots: list[ImageSlot] = Field(default_factory=list)  # rejected or failed


# ---------- step 5 ----------
class Finding(BaseModel):
    rule_id: str  # from 07 §4.1
    severity: Literal["block", "warn"]
    section_index: int
    field_path: str = Field(max_length=80)  # e.g. "headline", "items.2.text"
    excerpt: str = Field(max_length=300)
    suggestion: str = Field(max_length=600)


class AiFindings(BaseModel):  # tool submit_findings (AI does not give a score)
    findings: list[Finding]


class ComplianceReport(BaseModel):  # output of the step: regex + AI merged
    findings: list[Finding]
    claims_score: int = Field(ge=0, le=100)  # claims only; the page score is in 07 §9


# ---------- standalone AI calls outside the main steps ----------
class UrlFacts(BaseModel):  # tool submit_url_facts (05 §4.1)
    title: str = Field(max_length=120)
    facts: list[str] = Field(max_length=40)
    specs: dict[str, str] = Field(max_length=30)


class PaletteSuggestion(BaseModel):  # tool submit_palette (F05-2)
    primary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    background: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    text: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    rationale: str = Field(max_length=200)


class FieldRewrite(BaseModel):  # tool submit_rewrite (editor, one field)
    field_path: str
    new_value: str = Field(max_length=600)  # then re-validated against that field's limit


# ---------- step 6 and 7 ----------
class LayoutResult(BaseModel):
    metaobject_fields: dict[str, str]  # exactly the field keys of $app:page_content (03 §5.1), values as strings
    template_suffix: Literal["mosaiq"] | None  # only if Shop.mosaiq_templates_ready


class PublishResult(BaseModel):
    metaobject_gid: str
    shopify_page_gid: str | None
    product_gid: str | None
    status: Literal["draft"]
```

## 4. Step details

### 4.1 `import`
- `product_gid` → `product_get`; determine the source (06); `reference_image_urls` = the merchant's own product media.
- `manual` → create the product with `product_create_manual` (source `manual`).
- `source_url` → HTTP GET with user agent `MosaiqBot/1.0 (+https://mosaiq.<domain>/bot)`, timeout 10 s, max. 2 MB, respect `robots.txt`. Extract **facts only**, in own words, using an AI call (`UrlFacts`, prompt `prompts/url_facts.md`). No images, no verbatim sentences. Then job status `needs_input`: the merchant sees the `ManualProduct` form prefilled, adds price and photos and confirms → the product is created via `product_create_manual` and the job continues with `product_gid`. A URL therefore never directly produces a page without a product. Blocked/captcha/404 → `IMPORT_SOURCE_BLOCKED`, empty form with the URL filled in.
- No own product photos available → step `images` becomes `skipped` and the merchant sees "upload minimaal 1 productfoto voor AI-beelden" ("upload at least 1 product photo for AI images").

### 4.2 `research`
- Prompt: `docs/prompts/research.md`. Input: `ImportResult`, `niche_hint`, BrandKit tone.
- On success: job status → `needs_input` if `angle_id` is empty; the merchant chooses an angle (UI 09 §4). Then `run_job` again.

### 4.3 `copy`
- Prompt: `docs/prompts/copy.md` + niche guardrails from `docs/prompts/guardrails.md`.
- Section order per page type (fixed; the AI only fills it in):

| Page type | Sections in order |
| --- | --- |
| `pdp` | hero, benefits, problem_solution, how_it_works, specs*, comparison, faq, guarantee*, cta |
| `landing` | hero, problem_solution, benefits, how_it_works, comparison, faq, cta |
| `advertorial` | rich_text ×3–6 (narrative), cta |
| `listicle` | rich_text (intro), listicle_item ×5–7, cta |
| `home` | hero, benefits, how_it_works, faq, cta |
| `about` | rich_text ×2–3 |

\* `specs` only if `ImportResult.specs` has ≥ 2 keys; `guarantee` only if `Shop.guarantee_policy` is filled in. The code passes the final order (without omitted sections) to the prompt as `section_order`; the AI does not omit anything itself.

- `specs.rows[].label` must (after normalization: lowercase, whitespace trimmed) match a key from `ImportResult.specs`; the code compares them and removes rows without a match (and logs them).
- With `saved_template_id`, `section_order` comes from the template (F08) instead of from this table.
- On success: create `Page` with `sections = {content_locale: payload}`, `title` = `seo_title`, status `draft`.

### 4.4 `images`
- At most 5 images (slots). The count counts against plan limit `ai_images` (08); limit reached → fewer slots, never exceed it.
- Providers (00-decisions): primary `gemini-3.1-flash-image` via Vertex AI on the EU endpoint; if the fidelity check fails twice → one attempt with `gemini-3-pro-image` (stronger at product consistency, ±2× more expensive); provider error at Google → OpenAI `gpt-image-2.5-sunburst` via `/v1/images/edits` with `input_fidelity: "high"`.
- Resolution: 2K for `hero` and `lifestyle_*`, 1K for `detail_*` (≈ $0.10 and $0.067 per image respectively with `gemini-3.1-flash-image`, Vertex prices Sept. 2026).
- Reference images: at most 4 own product photos per shot (well within the limits of all three models).
- Every output: check product fidelity with a vision check (Anthropic, `LLM_MODEL_CHECK`): "Does this image show the same product as the reference (shape, color, logos, number of parts)? Answer JSON `{same_product: bool, issues: [...]}`". `same_product = false` → one new attempt; false again → skip the slot, `fidelity_ok = false`, do not publish.
- Own C2PA manifest with `c2pa-python` (≥ 0.37; `Builder`, `Signer.from_info(C2paSignerInfo(alg=PS256, sign_cert, private_key, ta_url))`, `builder.sign_file(src, dst, signer)`):
  - add the provider image as an ingredient with relationship **`parentOf`** and with `c2pa.opened` as the first action, so that the Google/OpenAI manifest is preserved; then action `c2pa.edited` with softwareAgent `Mosaiq`;
  - dev/staging: test certificates from `c2pa-rs` (manifest valid, but "untrusted");
  - production: certificate from a CA on the C2PA trust list (e.g. DigiCert, SSL.com); private key in a KMS/HSM or at minimum outside the repo with permissions 600 (11-ops).
- Then upload via `staged_uploads_create` → `file_create`.
- Generate alt text in the content language, max. 125 characters, descriptive, no claims.

### 4.5 `compliance_check`
- Deterministic rules first (07 §6: blocklists per language and niche) → `Finding`s.
- Then the AI check (`docs/prompts/compliance_check.md`) for what regex does not catch (medical claims, implicit green claims).
- `claims_score` = 100 − 25 per `block` − 5 per `warn`, minimum 0. The page score (`Page.compliance_score`) is computed by `compliance.score.page_score()` according to 07 §9.
- Findings are stored as `ClaimFinding` on the `Page` (with `locale`, `section_index`, `field_path`, `source`).
- At least one `block` → job status `needs_input`; for resuming see §1.

### 4.6 `layout` and `publish`
- `layout` converts `SectionsPayload` + images into `metaobject_fields` (JSON strings) and sets `template_suffix = "mosaiq"` if `Shop.mosaiq_templates_ready` (templates `product.mosaiq` / `page.mosaiq`, 09), otherwise `None`.
- `publish` executes, in this order: per language `metaobject_upsert` (status `DRAFT`) → for landing/advertorial/listicle/about `page_create` or `page_update` (`isPublished:false`) → set metafield `page` (list with all language entries) on the product, page or shop (for `home`) → `Page.version += 1`, store the GIDs. The metafield may already be set at the draft stage: a metaobject in status `DRAFT` is not visible on the storefront.
- Going live (`go_live`, F07) only does: metaobject(s) `ACTIVE`, page `isPublished:true`, `Page.status = live`.
- `publish` first checks GPSR completeness (07 §5). Incomplete → `GPSR_INCOMPLETE`, no write actions.

## 5. Error codes (`generator.errors`)

| Code | Meaning | Merchant-facing text (NL) | Merchant-facing text (EN) |
| --- | --- | --- | --- |
| `IMPORT_NOT_FOUND` | Product does not exist (any more) | Dit product bestaat niet meer in je winkel. | This product no longer exists in your store. |
| `IMPORT_SOURCE_BLOCKED` | URL cannot be fetched | We konden deze link niet lezen. Vul de productgegevens handmatig in. | We couldn't read this link. Please enter the product details manually. |
| `AI_SCHEMA_INVALID` | Output unusable after repair | Het genereren lukte niet. Probeer het opnieuw; er is niets in rekening gebracht. | Generation failed. Please try again; you have not been charged. |
| `AI_PROVIDER_ERROR` | Provider unreachable | De AI-dienst is tijdelijk niet bereikbaar. We proberen het automatisch opnieuw. | The AI service is temporarily unavailable. We'll retry automatically. |
| `AI_BUDGET_EXCEEDED` | Job cost limit | Deze opdracht was te groot. Probeer minder pagina's tegelijk. | This request was too large. Try fewer pages at a time. |
| `IMAGE_FIDELITY_REJECTED` | Image deviated from product | Eén of meer beelden leken niet genoeg op je product en zijn weggelaten. | One or more images did not look enough like your product and have been left out. |
| `COMPLIANCE_BLOCKED` | Prohibited claim | Pas de gemarkeerde tekst aan voordat je publiceert. | Edit the highlighted text before you publish. |
| `GPSR_INCOMPLETE` | GPSR data missing | Vul de fabrikant- en veiligheidsgegevens in om te kunnen publiceren. | Fill in the manufacturer and safety details to be able to publish. |
| `PLAN_LIMIT_REACHED` | Plan limit | Je hebt de limiet van je plan bereikt. Upgrade of wacht tot de nieuwe periode. | You have reached your plan's limit. Upgrade or wait for the new period. |
| `SHOPIFY_USER_ERROR` | `userErrors` from Shopify | Shopify weigerde de wijziging: {message} | Shopify rejected the change: {message} |
| `SHOPIFY_THROTTLED` | Rate limit after retries | Shopify is druk. We proberen het over een paar minuten opnieuw. | Shopify is busy. We'll try again in a few minutes. |

Limits are **reserved** at job start (`reserved_*` in `UsageCounter`, in the same transaction as the limit check, with `select_for_update`): 1 store generation for `kind=store`, 5 images per page. On completion: convert the consumed amounts from reserved to consumed, release the rest. A failed job releases everything, except images that have already been uploaded. This way two parallel jobs cannot exceed the limit.
