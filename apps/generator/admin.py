"""Admin for generator."""

from django.contrib import admin

from .models import AiCall, GenerationJob, JobStep, Page


class JobStepInline(admin.TabularInline):
    model = JobStep
    extra = 0
    readonly_fields = ("name", "status", "attempt", "ai_cost_usd", "started_at", "finished_at")


@admin.register(GenerationJob)
class GenerationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "shop", "kind", "page_type", "status", "current_step", "ai_cost_usd", "created_at")
    list_filter = ("kind", "status", "page_type")
    search_fields = ("shop__domain", "idempotency_key")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
    inlines = [JobStepInline]


@admin.register(JobStep)
class JobStepAdmin(admin.ModelAdmin):
    list_display = ("job", "name", "status", "attempt", "ai_cost_usd", "started_at", "finished_at")
    list_filter = ("name", "status")
    search_fields = ("job__idempotency_key",)


@admin.register(AiCall)
class AiCallAdmin(admin.ModelAdmin):
    list_display = (
        "shop",
        "purpose",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "success",
        "created_at",
    )
    list_filter = ("purpose", "provider", "success")
    search_fields = ("shop__domain",)


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "shop", "page_type", "status", "compliance_score", "version", "created_at")
    list_filter = ("page_type", "status")
    search_fields = ("shop__domain", "title", "product_gid")
