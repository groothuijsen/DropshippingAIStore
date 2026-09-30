"""Lighthouse check for generated PDP pages.

See docs/10-testing.md §5 (Lighthouse mobile ≥ 85).
Runs Lighthouse CLI against a URL and checks the performance score.

Usage:
    python scripts/lighthouse_check.py <url> [--min-score 85] [--mobile]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run_lighthouse(url: str, mobile: bool = True) -> dict:
    """Run Lighthouse CLI against a URL and return the JSON report."""
    lighthouse_bin = shutil.which("lighthouse")
    lighthouse_cmd = ["npx", "-y", "lighthouse"] if lighthouse_bin is None else [lighthouse_bin]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_path = tmp.name

    cmd = [
        *lighthouse_cmd,
        url,
        "--output=json",
        f"--output-path={output_path}",
        "--chrome-flags=--headless",
        "--quiet",
    ]
    if mobile:
        cmd.append("--form-factor=mobile")
        cmd.append("--screenEmulation.mobile")
    else:
        cmd.append("--preset=desktop")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        raise RuntimeError(f"Lighthouse failed: {result.stderr[:500]}")

    with open(output_path) as f:
        report = json.load(f)

    Path(output_path).unlink(missing_ok=True)
    return report


def get_performance_score(report: dict) -> float:
    """Extract the performance score from a Lighthouse report."""
    return report.get("categories", {}).get("performance", {}).get("score", 0.0) or 0.0


def get_metric_value(report: dict, metric_id: str) -> float | None:
    """Extract a metric value (e.g. LCP, FCP, CLS) from a Lighthouse report."""
    audits = report.get("audits", {})
    audit = audits.get(metric_id, {})
    return audit.get("numericValue")


def check_url(url: str, min_score: int = 85, mobile: bool = True) -> dict:
    """Run Lighthouse and check if the score meets the minimum."""
    report = run_lighthouse(url, mobile=mobile)
    score = get_performance_score(report)
    score_pct = round(score * 100)

    lcp = get_metric_value(report, "largest-contentful-paint")
    fcp = get_metric_value(report, "first-contentful-paint")
    cls = get_metric_value(report, "cumulative-layout-shift")

    result = {
        "url": url,
        "score": score_pct,
        "min_score": min_score,
        "passed": score_pct >= min_score,
        "lcp_ms": round(lcp) if lcp else None,
        "fcp_ms": round(fcp) if fcp else None,
        "cls": round(cls, 3) if cls else None,
        "mobile": mobile,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Lighthouse check for PDP pages")
    parser.add_argument("url", help="URL to check")
    parser.add_argument("--min-score", type=int, default=85, help="Minimum performance score")
    parser.add_argument("--desktop", action="store_true", help="Use desktop preset instead of mobile")
    args = parser.parse_args()

    try:
        result = check_url(args.url, min_score=args.min_score, mobile=not args.desktop)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"URL: {result['url']}")
    print(f"Score: {result['score']}/100 (min: {result['min_score']})")
    print(f"LCP: {result['lcp_ms']}ms")
    print(f"FCP: {result['fcp_ms']}ms")
    print(f"CLS: {result['cls']}")
    print(f"Result: {'PASS' if result['passed'] else 'FAIL'}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
