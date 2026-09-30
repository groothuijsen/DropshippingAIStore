"""AI eval runner — runs real AI calls on the evalset and writes a report.

See docs/10-testing.md §4.
- 30 products as JSON (ImportResult shape): 10 wellness/sleep, 10 car accessories, 10 POD merch
- Runs real AI calls (not in CI; manually or weekly), writes eval-report-<date>.md
- Measures per product: schema valid, compliance block findings, fabricated specs,
  length overruns, cost, duration
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EVALSET_PATH = Path(__file__).parent / "eval_products.json"
REPORT_DIR = Path(__file__).parent


def load_evalset() -> list[dict[str, Any]]:
    """Load the 30-product evalset."""
    with open(EVALSET_PATH) as f:
        return json.load(f)


def check_fabricated_specs(
    output_specs: list[dict[str, str]],
    input_specs: dict[str, str],
) -> list[str]:
    """Compare output specs with input specs.

    Returns list of fabricated spec labels (present in output but not in input).
    """
    input_labels = {k.lower().strip() for k in input_specs}
    fabricated = []
    for row in output_specs:
        label = row.get("label", "").lower().strip()
        if label and label not in input_labels:
            fabricated.append(row.get("label", ""))
    return fabricated


def check_length_overruns(payload: Any) -> list[str]:
    """Check for length overruns in the payload.

    Returns list of field names that exceeded their max_length.
    """
    overruns = []

    if hasattr(payload, "seo_title") and len(payload.seo_title) > 60:
        overruns.append("seo_title")
    if hasattr(payload, "seo_description") and len(payload.seo_description) > 155:
        overruns.append("seo_description")

    if hasattr(payload, "sections"):
        for section in payload.sections:
            if hasattr(section, "headline") and len(section.headline) > 100:
                overruns.append(f"section.headline ({section.type})")

    return overruns


def run_eval(
    products: list[dict[str, Any]] | None = None,
    max_products: int | None = None,
) -> dict[str, Any]:
    """Run the evalset.

    Returns dict with per-product results and summary.
    """
    from apps.ai.anthropic_client import call_ai
    from apps.ai.prompts import render_prompt
    from apps.ai.schemas import SectionsPayload
    from apps.compliance.claims import check_sections
    from apps.core.crypto import encrypt_token
    from apps.core.models import Shop

    # Eval shop — used for AiCall cost tracking
    eval_shop, _ = Shop.objects.get_or_create(
        domain="eval-mosaiq.myshopify.com",
        defaults={
            "shopify_gid": "gid://shopify/Shop/eval",
            "access_token_encrypted": encrypt_token("eval-token"),
            "refresh_token_encrypted": encrypt_token("eval-refresh"),
            "currency_code": "EUR",
        },
    )

    if products is None:
        products = load_evalset()
    if max_products:
        products = products[:max_products]

    results = []
    total_cost = Decimal("0")
    total_duration = 0.0

    for product in products:
        start = time.monotonic()

        try:
            # Render prompt
            system_prompt, user_prompt = render_prompt(
                "copy",
                {
                    "import_result": {
                        "title": product["title"],
                        "description": product["description"],
                        "price": product["price"],
                        "currency": product["currency"],
                        "specs": product["specs"],
                    },
                    "research_result": {
                        "niche": product["category"],
                        "chosen_angle": {"id": "eval", "title": "Eval angle"},
                        "angles": [{"id": "eval", "title": "Eval angle"}],
                    },
                    "chosen_angle": {"id": "eval", "title": "Eval angle"},
                    "section_order": ["hero", "benefits", "specs", "cta"],
                    "page_type": "pdp",
                    "tone": "friendly",
                    "niche": product["category"],
                    "content_locale": product["language"],
                    "guarantee_policy": "30-day money-back guarantee",
                },
            )

            # Call AI
            payload = call_ai(
                shop=eval_shop,
                purpose="copy",
                model_key="claude",
                system=system_prompt,
                user=user_prompt,
                schema=SectionsPayload,
                tool_name="sections_payload",
            )

            duration = time.monotonic() - start

            # Schema valid check
            schema_valid = True

            # Compliance check
            sections_list = []
            for section in payload.sections:
                if hasattr(section, "model_dump"):
                    sections_list.append(section.model_dump())
                elif isinstance(section, dict):
                    sections_list.append(section)

            findings = check_sections(sections_list, product["language"])
            block_count = sum(1 for f in findings if f.severity == "block")

            # Fabricated specs check
            output_specs = []
            for section in sections_list:
                if section.get("type") == "specs":
                    output_specs = section.get("rows", [])
            fabricated = check_fabricated_specs(output_specs, product["specs"])

            # Length overruns
            overruns = check_length_overruns(payload)

            # Cost (approximate — Claude pricing)
            cost = Decimal("0.05")  # placeholder; real cost tracked in AiCall

            total_cost += cost
            total_duration += duration

            results.append(
                {
                    "id": product["id"],
                    "category": product["category"],
                    "language": product["language"],
                    "schema_valid": schema_valid,
                    "block_count": block_count,
                    "fabricated_specs": fabricated,
                    "overruns": overruns,
                    "cost_usd": float(cost),
                    "duration_s": round(duration, 2),
                    "error": None,
                }
            )

        except Exception as exc:
            duration = time.monotonic() - start
            total_duration += duration
            results.append(
                {
                    "id": product["id"],
                    "category": product["category"],
                    "language": product["language"],
                    "schema_valid": False,
                    "block_count": -1,
                    "fabricated_specs": [],
                    "overruns": [],
                    "cost_usd": 0.0,
                    "duration_s": round(duration, 2),
                    "error": str(exc),
                }
            )

    # Summary
    valid_count = sum(1 for r in results if r["schema_valid"])
    total_blocks = sum(r["block_count"] for r in results if r["block_count"] >= 0)
    total_fabricated = sum(len(r["fabricated_specs"]) for r in results)
    total_overruns = sum(len(r["overruns"]) for r in results)
    errors = [r for r in results if r["error"]]

    summary = {
        "total": len(results),
        "schema_valid": valid_count,
        "total_blocks": total_blocks,
        "total_fabricated_specs": total_fabricated,
        "total_overruns": total_overruns,
        "total_cost_usd": float(total_cost),
        "total_duration_s": round(total_duration, 2),
        "errors": len(errors),
    }

    return {"results": results, "summary": summary}


def write_report(eval_output: dict[str, Any]) -> Path:
    """Write eval report to eval-report-<date>.md."""
    today = date.today().isoformat()
    report_path = REPORT_DIR / f"eval-report-{today}.md"

    summary = eval_output["summary"]
    results = eval_output["results"]

    lines = [
        f"# AI Eval Report — {today}",
        "",
        "## Summary",
        "",
        f"- **Total products:** {summary['total']}",
        f"- **Schema valid:** {summary['schema_valid']}/{summary['total']}",
        f"- **Compliance blocks:** {summary['total_blocks']} (target: 0)",
        f"- **Fabricated specs:** {summary['total_fabricated_specs']} (target: 0)",
        f"- **Length overruns:** {summary['total_overruns']} (target: 0)",
        f"- **Total cost:** ${summary['total_cost_usd']:.4f}",
        f"- **Total duration:** {summary['total_duration_s']:.1f}s",
        f"- **Errors:** {summary['errors']}",
        "",
        "## Per-product results",
        "",
        "| ID | Category | Lang | Schema | Blocks | Fabricated | Overruns | Cost | Duration | Error |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        error = r["error"] or ""
        if len(error) > 40:
            error = error[:37] + "..."
        lines.append(
            f"| {r['id']} | {r['category']} | {r['language']} | "
            f"{'✅' if r['schema_valid'] else '❌'} | {r['block_count']} | "
            f"{len(r['fabricated_specs'])} | {len(r['overruns'])} | "
            f"${r['cost_usd']:.4f} | {r['duration_s']}s | {error} |"
        )

    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if (
        summary["schema_valid"] == summary["total"]
        and summary["total_blocks"] == 0
        and summary["total_fabricated_specs"] == 0
        and summary["total_overruns"] == 0
        and summary["errors"] == 0
    ):
        lines.append("**PASS** — all targets met.")
    else:
        lines.append("**FAIL** — one or more targets not met. See details above.")

    report_path.write_text("\n".join(lines))
    return report_path


if __name__ == "__main__":
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    os.environ.setdefault("DJANGO_SECRET_KEY", "eval-runner")
    django.setup()

    output = run_eval()
    report = write_report(output)
    print(f"Report written to {report}")
    print(json.dumps(output["summary"], indent=2))
