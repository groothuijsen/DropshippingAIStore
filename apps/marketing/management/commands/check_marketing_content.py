"""Validate marketing content files (F19-2, 13 §4).

Fails when a file violates its section schema, when a referenced claim is
missing from docs/marketing/claims.md or is not verified, or when the
language sets diverge. Runs in CI; a failure blocks the merge.
"""

from __future__ import annotations

import pathlib
import re

from django.core.management.base import BaseCommand, CommandError

from apps.marketing.content import LANGUAGES, list_pages, load_page
from apps.marketing.schemas import collect_claim_ids, validate_sections

CLAIMS_FILE = pathlib.Path(__file__).resolve().parents[4] / "docs" / "marketing" / "claims.md"


def _claim_status() -> dict[str, str]:
    statuses: dict[str, str] = {}
    if not CLAIMS_FILE.exists():
        return statuses
    for line in CLAIMS_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*(C-\d+)\s*\|", line)
        if match:
            claim_id = match.group(1)
            statuses[claim_id] = "unverified" if "unverified" in line.lower() else "verified"
    return statuses


class Command(BaseCommand):
    help = "Validate marketing content (schemas, claims, language parity)."

    def handle(self, *args, **options):
        errors: list[str] = []
        claims = _claim_status()
        page_sets: dict[str, set[str]] = {}

        for lang in LANGUAGES:
            pages = list_pages(lang)
            page_sets[lang] = set(pages)
            for slug in pages:
                try:
                    page = load_page(lang, slug)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{lang}/{slug}.md: {exc}")
                    continue
                if not page["title"]:
                    errors.append(f"{lang}/{slug}.md: missing title")
                errors.extend(f"{lang}/{slug}.md: {e}" for e in validate_sections(page["sections"]))
                for section in page["sections"]:
                    for claim_id in collect_claim_ids(section):
                        if claim_id not in claims:
                            errors.append(f"{lang}/{slug}.md: claim {claim_id} not in claims.md")
                        elif claims[claim_id] != "verified":
                            errors.append(f"{lang}/{slug}.md: claim {claim_id} is not verified")

        langs = list(page_sets)
        if langs:
            reference = page_sets[langs[0]]
            for lang in langs[1:]:
                missing = reference - page_sets[lang]
                extra = page_sets[lang] - reference
                if missing:
                    errors.append(f"{lang}: missing pages {sorted(missing)}")
                if extra:
                    errors.append(f"{lang}: extra pages {sorted(extra)}")

        if errors:
            raise CommandError("marketing content invalid:\n" + "\n".join(errors))
        self.stdout.write(self.style.SUCCESS(f"marketing content OK ({', '.join(LANGUAGES)})"))
