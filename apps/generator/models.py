"""Models for generator — GenerationJob, JobStep, AiCall, Page.

See docs/02-data-model.md §generator, docs/05-ai-pipeline.md.
"""

import uuid

from django.db import models


class JobKind(models.TextChoices):
    STORE = "store", "Store"
    PAGE = "page", "Page"


class JobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    NEEDS_INPUT = "needs_input", "Needs input"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class StepName(models.TextChoices):
    IMPORT = "import", "Import"
    RESEARCH = "research", "Research"
    COPY = "copy", "Copy"
    IMAGES = "images", "Images"
    COMPLIANCE_CHECK = "compliance_check", "Compliance check"
    LAYOUT = "layout", "Layout"
    PUBLISH = "publish", "Publish"


class StepStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class PageType(models.TextChoices):
    PDP = "pdp", "PDP"
    LANDING = "landing", "Landing"
    ADVERTORIAL = "advertorial", "Advertorial"
    LISTICLE = "listicle", "Listicle"
    HOME = "home", "Home"
    ABOUT = "about", "About"


class PageStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    LIVE = "live", "Live"
    ARCHIVED = "archived", "Archived"


class GenerationJob(models.Model):
    """A single generation job that runs through a fixed sequence of steps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="jobs")
    kind = models.CharField(max_length=10, choices=JobKind.choices)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="For kind=store: child jobs (home, pdp, about) reference the store job",
    )
    page_type = models.CharField(
        max_length=20,
        choices=PageType.choices,
        null=True,
        blank=True,
        help_text="Null only for kind=store",
    )
    content_locale = models.CharField(max_length=5)
    input = models.JSONField(help_text="JobInput.model_dump(mode='json')")
    status = models.CharField(
        max_length=15,
        choices=JobStatus.choices,
        default=JobStatus.QUEUED,
    )
    current_step = models.CharField(
        max_length=40,
        choices=StepName.choices,
        null=True,
        blank=True,
    )
    error_code = models.CharField(max_length=60, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    ai_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(
        max_length=64,
        help_text="Unique per shop; prevents duplicate jobs on double-click",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "idempotency_key"],
                name="unique_job_idempotency_per_shop",
            ),
        ]
        indexes = [
            models.Index(fields=["shop", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}/{self.page_type or 'store'} ({self.status}) — {self.shop.domain}"


class JobStep(models.Model):
    """Individual step within a job. Succeeded steps are skipped on restart."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(GenerationJob, on_delete=models.CASCADE, related_name="steps")
    name = models.CharField(max_length=30, choices=StepName.choices)
    status = models.CharField(
        max_length=15,
        choices=StepStatus.choices,
        default=StepStatus.PENDING,
    )
    attempt = models.PositiveSmallIntegerField(default=0)
    output = models.JSONField(null=True, blank=True, help_text="Validated output checkpoint")
    ai_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "name"],
                name="unique_job_step_name",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.status}) — attempt {self.attempt}"


class AiCallPurpose(models.TextChoices):
    RESEARCH = "research", "Research"
    COPY = "copy", "Copy"
    IMAGE = "image", "Image"
    FIDELITY = "fidelity", "Fidelity"
    COMPLIANCE = "compliance", "Compliance"
    URL_FACTS = "url_facts", "URL facts"
    PALETTE = "palette", "Palette"
    REWRITE = "rewrite", "Rewrite"
    TRANSLATE = "translate", "Translate"
    SHOT_PLAN = "shot_plan", "Shot plan"


class AiProvider(models.TextChoices):
    ANTHROPIC = "anthropic", "Anthropic"
    VERTEX = "vertex", "Vertex AI"
    OPENAI = "openai", "OpenAI"


class AiCall(models.Model):
    """Log entry for every AI API call — cost tracking, debugging, audit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey(
        "core.Shop",
        on_delete=models.CASCADE,
        related_name="ai_calls",
        help_text="CASCADE; also for calls outside a job",
    )
    step = models.ForeignKey(
        JobStep,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_calls",
        help_text="Null for palette, rewrite, translate",
    )
    purpose = models.CharField(max_length=40, choices=AiCallPurpose.choices)
    provider = models.CharField(max_length=20, choices=AiProvider.choices)
    model = models.CharField(max_length=80)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    images = models.PositiveSmallIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=4)
    duration_ms = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["shop", "purpose"]),
            models.Index(fields=["shop", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.purpose} via {self.provider}/{self.model} (${self.cost_usd})"


class Page(models.Model):
    """A generated page — created after copy step, status draft, local only."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shop = models.ForeignKey("core.Shop", on_delete=models.CASCADE, related_name="pages")
    job = models.ForeignKey(
        GenerationJob,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pages",
    )
    page_type = models.CharField(max_length=20, choices=PageType.choices)
    title = models.CharField(max_length=120, help_text="Internal and Shopify page title")
    angle = models.CharField(max_length=120, blank=True, help_text="Chosen angle")
    content_locale = models.CharField(max_length=5)
    sections = models.JSONField(
        default=dict,
        help_text='SectionsPayload per language: {"nl": {...}, "de": {...}}',
    )
    images = models.JSONField(
        default=dict,
        help_text='{"hero": "gid://shopify/MediaImage/…", "lifestyle_1": …}',
    )
    seo_title = models.CharField(max_length=60, blank=True)
    seo_description = models.CharField(max_length=155, blank=True)
    ai_image_disclosure = models.BooleanField(default=True)
    product_gid = models.CharField(max_length=255, null=True, blank=True)
    shopify_page_gid = models.CharField(max_length=255, null=True, blank=True)
    shopify_page_handle = models.CharField(max_length=255, null=True, blank=True)
    metaobject_handles = models.JSONField(
        default=dict,
        help_text='Per language: {"nl": "mq-<short>-<uuid8>-nl"}',
    )
    metaobject_gids = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=10,
        choices=PageStatus.choices,
        default=PageStatus.DRAFT,
    )
    compliance_score = models.PositiveSmallIntegerField(default=0)
    variant_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="variants",
        help_text="For A/B in v1.1",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["shop", "status"]),
            models.Index(fields=["shop", "product_gid"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.page_type}) — {self.status}"
