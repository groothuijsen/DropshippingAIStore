"""Pydantic v2 schemas for AI pipeline output validation.

See docs/05-ai-pipeline.md §3.
Every AI output MUST be validated against these schemas before use.
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

Locale = Literal["nl", "en", "de"]
Niche = Literal["wellness_sleep", "auto_accessories", "pod_merch", "other"]


# ── Input ─────────────────────────────────────────────────────────────────


class ManualProduct(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=20, max_length=5000)
    specs: dict[str, str] = Field(default_factory=dict, max_length=30)
    price: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class JobInput(BaseModel):
    kind: Literal["store", "page"]
    saved_template_id: str | None = None
    product_gid: str | None = None
    manual: ManualProduct | None = None
    source_url: HttpUrl | None = None
    page_type: Literal["pdp", "landing", "advertorial", "listicle", "home", "about", "faq", "shipping", "returns"] | None = None
    content_locale: Locale
    niche_hint: Niche | None = None
    angle_id: str | None = None
    style_preset: Literal["clean", "bold", "organic", "luxe", "tech", "soft"]

    @model_validator(mode="after")
    def exactly_one_source(self):
        given = [x is not None for x in (self.product_gid, self.manual, self.source_url)]
        if sum(given) != 1:
            raise ValueError("exactly one of product_gid, manual or source_url is required")
        return self


# ── Step 1: import ────────────────────────────────────────────────────────


class ImportResult(BaseModel):
    product_gid: str | None
    source_app: Literal["manual", "dsers", "cj", "zendrop", "autods", "printify", "unknown_app"]
    title: str
    facts: list[str] = Field(max_length=40)
    specs: dict[str, str]
    reference_image_urls: list[str] = Field(max_length=8)
    price: Decimal | None
    currency: str | None
    locked_fields: list[str]


# ── Step 2: research ──────────────────────────────────────────────────────


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
    claim_risks: list[str] = Field(max_length=10)


# ── Step 3: sections ──────────────────────────────────────────────────────


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
    label: str = Field(max_length=60)
    value: str = Field(max_length=120)


class Specs(BaseModel):
    type: Literal["specs"] = "specs"
    rows: list[SpecRow] = Field(min_length=2, max_length=20)


class ComparisonRow(BaseModel):
    feature: str = Field(max_length=80)
    ours: bool
    other: bool


class Comparison(BaseModel):
    type: Literal["comparison"] = "comparison"
    ours_label: str = Field(max_length=30)
    other_label: str = Field(max_length=30)
    rows: list[ComparisonRow] = Field(min_length=3, max_length=8)


class Faq(BaseModel):
    type: Literal["faq"] = "faq"
    items: list[FaqItem] = Field(min_length=4, max_length=8)


class Guarantee(BaseModel):
    type: Literal["guarantee"] = "guarantee"
    text: str = Field(max_length=300)


class RichText(BaseModel):
    type: Literal["rich_text"] = "rich_text"
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
    Hero
    | Benefits
    | ProblemSolution
    | HowItWorks
    | Specs
    | Comparison
    | Faq
    | Guarantee
    | RichText
    | ListicleItem
    | Cta,
    Field(discriminator="type"),
]


class SectionsPayload(BaseModel):
    locale: Locale
    page_type: Literal["pdp", "landing", "advertorial", "listicle", "home", "about"]
    seo_title: str = Field(max_length=60)
    seo_description: str = Field(max_length=155)
    sections: list[Section] = Field(min_length=2, max_length=14)


# ── Step 4: images ────────────────────────────────────────────────────────

ImageSlot = Literal["hero", "lifestyle_1", "lifestyle_2", "detail_1", "detail_2"]


class ImageShot(BaseModel):
    slot: ImageSlot
    purpose: str = Field(max_length=120)
    prompt: str = Field(max_length=1200)
    aspect_ratio: Literal["1:1", "4:5", "16:9"]
    reference_image_urls: list[str] = Field(min_length=1, max_length=4)
    people_allowed: bool = False


class ImagePlan(BaseModel):
    shots: list[ImageShot] = Field(min_length=0, max_length=5)


class FidelityResult(BaseModel):
    same_product: bool
    issues: list[str] = Field(max_length=10)


class ImageOut(BaseModel):
    slot: ImageSlot
    file_gid: str
    provider: Literal["vertex", "openai"]
    c2pa_signed: Literal[True]
    alt: str = Field(max_length=125)


class ImageResult(BaseModel):
    images: list[ImageOut] = Field(max_length=5)
    rejected_slots: list[ImageSlot] = Field(default_factory=list)


# ── Step 5: compliance check ──────────────────────────────────────────────


class Finding(BaseModel):
    rule_id: str
    severity: Literal["block", "warn"]
    section_index: int
    field_path: str = Field(max_length=80)
    excerpt: str = Field(max_length=300)
    suggestion: str = Field(max_length=600)


class AiFindings(BaseModel):
    findings: list[Finding]


class ComplianceReport(BaseModel):
    findings: list[Finding]
    claims_score: int = Field(ge=0, le=100)


# ── Standalone AI calls ───────────────────────────────────────────────────


class UrlFacts(BaseModel):
    title: str = Field(max_length=120)
    facts: list[str] = Field(max_length=40)
    specs: dict[str, str] = Field(max_length=30)


class PaletteSuggestion(BaseModel):
    primary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    background: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    text: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    rationale: str = Field(max_length=200)


class BrandProposal(BaseModel):
    """F15-5 brand proposal — tool submit_brand (12 §3)."""

    tone: Literal["warm", "premium", "playful", "clinical", "sporty"]
    style_preset: Literal["clean", "bold", "organic", "luxe", "tech", "soft"]
    palette: PaletteSuggestion  # contrast re-checked in code (F05-3)
    font_heading: str  # key from themes/fonts.py; validated against the list
    font_body: str
    tagline: str = Field(max_length=60)
    rationale: str = Field(max_length=240)


class FieldRewrite(BaseModel):
    field_path: str
    new_value: str = Field(max_length=600)


# ── Step 6 and 7 ──────────────────────────────────────────────────────────


class ProductIdea(BaseModel):
    title: str = Field(max_length=80)
    why: str = Field(max_length=200)
    search_phrases: list[str] = Field(min_length=2, max_length=4)
    target_price_band: str = Field(max_length=30)  # e.g. "€25–35 incl. VAT"
    eu_notes: list[str] = Field(max_length=4)


class ProductIdeas(BaseModel):  # tool submit_product_ideas (F15-6)
    ideas: list[ProductIdea] = Field(min_length=5, max_length=10)
    avoid: list[str] = Field(max_length=6)


class RewriteResult(BaseModel):
    """Result of a field rewrite (F07 criterion 3)."""

    rewritten: str = Field(max_length=500)


class LayoutResult(BaseModel):
    metaobject_fields: dict[str, str]
    template_suffix: Literal["mosaiq"] | None


class PublishResult(BaseModel):
    metaobject_gid: str
    shopify_page_gid: str | None
    product_gid: str | None
    status: Literal["draft"]


# ── Store-builder wizard (F15, 12 §3) ─────────────────────────────────────

Market = Literal["NL", "BE", "DE", "AT", "FR", "LU", "GB", "IE", "OTHER_EU"]
PriceLevel = Literal["budget", "mid", "premium"]


class NicheBrief(BaseModel):
    description: str = Field(min_length=20, max_length=500)
    markets: list[Market] = Field(min_length=1, max_length=5)
    content_locales: list[Locale] = Field(min_length=1, max_length=3)
    audience: str = Field(max_length=200)
    price_level: PriceLevel
    import_app: Literal["dsers", "cj", "zendrop", "autods", "printify", "printful", "manual", "other"]


class NameIdea(BaseModel):
    name: str = Field(min_length=3, max_length=14, pattern=r"^[A-Za-z][A-Za-z0-9]*$")
    rationale: str = Field(max_length=160)
    pronunciation_ok: list[Locale]


class NameSuggestions(BaseModel):  # tool submit_names
    names: list[NameIdea] = Field(min_length=8, max_length=8)


# ── Store structure (12 §3, T-115/F15-8) ──────────────────────────────────


class CollectionPlan(BaseModel):
    title: str = Field(max_length=60)
    description: str = Field(max_length=300)
    product_gids: list[str] = Field(min_length=1, max_length=20)  # subset of selection


class MenuItemPlan(BaseModel):
    title: str = Field(max_length=40)
    target: Literal["frontpage", "collection", "page", "catalog"]
    ref: str | None = None  # collection title or page_type; GID resolved at build time


class StoreStructure(BaseModel):  # tool submit_structure
    collections: list[CollectionPlan] = Field(min_length=1, max_length=6)
    menu: list[MenuItemPlan] = Field(min_length=3, max_length=8)
    pages: list[Literal["about", "faq", "shipping", "returns"]] = Field(min_length=2, max_length=4)


# ── Standard pages: faq / shipping / returns (12 §3, T-116) ──────────────


class StandardFaqItem(BaseModel):
    question: str = Field(max_length=160)
    answer: str = Field(max_length=600)


class StandardPageContent(BaseModel):
    page_type: Literal["about", "faq", "shipping", "returns"]
    title: str = Field(max_length=120)
    intro: str = Field(max_length=800)
    faq_items: list[StandardFaqItem] = Field(max_length=12)


class StandardPages(BaseModel):  # tool submit_standard_pages
    pages: list[StandardPageContent] = Field(min_length=1, max_length=4)


# ── F16 plain-language page edits (12 §3) ──────────────────────────────────

EditOpKind = Literal["replace_field", "add_section", "remove_section", "move_section"]


class EditOp(BaseModel):
    op: EditOpKind
    section_index: int = Field(ge=0, le=13)
    field: str | None = None  # replace_field only; dotted path inside the section, e.g. "items.1.text"
    value: str | None = Field(default=None, max_length=1200)  # replace_field only
    section: Section | None = None  # add_section only (existing discriminated union, 05 §3)
    to_index: int | None = Field(default=None, ge=0, le=13)  # move_section only


class PageEditResult(BaseModel):  # tool submit_page_edit
    operations: list[EditOp] = Field(min_length=1, max_length=10)
    summary: str = Field(max_length=200)  # shown to the merchant, in the UI language
