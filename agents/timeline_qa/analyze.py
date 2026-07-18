"""
Timeline QA — run packing/SAP tests and report template coverage gaps.

Usage:
  python -m agents.timeline_qa.analyze
  python -m agents.timeline_qa.analyze --slack
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.paths import BACKEND_ROOT, REPORTS_ROOT, ensure_work_dirs
from agents.shared.schemas import AnalyticsReport, Recommendation, load_dotenv_file, write_json
from agents.test_runner.run_tests import run_suite


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")


def _list_sap_templates() -> list[str]:
    root = BACKEND_ROOT / "sap_templates"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.glob("*.json"))


def analyze(*, run_tests: bool = True) -> AnalyticsReport:
    ensure_work_dirs()
    templates = _list_sap_templates()
    metrics: dict = {
        "sap_template_count": len(templates),
        "sap_templates": templates,
    }
    notes: list[str] = [
        "SAP hybrid is live for templated UP majors only; others use Layer-1 credit-band packer.",
        "Audit engine remains source of truth — SAP supplies order/completeness/credit balance.",
        "Do not LLM-scrape SAPs; use scripts/scrape_sap.py (CourseLeaf table.sc_plangrid).",
    ]
    recs: list[Recommendation] = []

    if len(templates) < 5:
        recs.append(
            Recommendation(
                id="timeline-expand-sap-templates",
                area="timeline",
                severity="medium",
                title="Expand SAP template set beyond Accounting + Marketing",
                rationale=(
                    f"Only {len(templates)} SAP template(s) present ({', '.join(templates) or 'none'}). "
                    "docs/timeline-sap-hybrid.md Phase 4b: scale to full UP major list via scrape_sap.py."
                ),
                suggested_owner="human",
                verify_steps=[
                    "cd backend && python scripts/scrape_sap.py --dry-run",
                    "cd backend && python -m pytest tests/test_plan_templates.py tests/test_scrape_sap.py -v",
                ],
                claude_md_refs=["Suggested Academic Plans (SAP hybrid)", "docs/timeline-sap-hybrid.md"],
            )
        )

    if run_tests:
        report = run_suite("timeline")
        metrics["pytest_ok"] = report.ok
        metrics["pytest_passed"] = report.passed
        metrics["pytest_failed"] = report.failed
        metrics["pytest_log"] = report.log_path
        if not report.ok:
            recs.append(
                Recommendation(
                    id="timeline-pytest-failing",
                    area="timeline",
                    severity="critical",
                    title="Fix failing timeline/SAP pytest suite",
                    rationale=f"Failures: {', '.join(report.failing_nodeids) or 'see log'}",
                    suggested_owner="human or implement_fix",
                    verify_steps=[
                        "cd backend && python -m pytest tests/test_timeline_packing.py tests/test_sap_schedule.py "
                        "tests/test_plan_templates.py tests/test_scrape_sap.py -v",
                    ],
                    claude_md_refs=["Timeline semester projection", "SAP hybrid"],
                )
            )
        else:
            notes.append(f"Timeline/SAP pytest suite green ({report.passed} passed).")

    out = AnalyticsReport(
        area="timeline",
        title="Timeline / SAP QA",
        metrics=metrics,
        notes=notes,
        recommendations=recs,
    )
    write_json(REPORTS_ROOT / "timeline-qa-latest.json", out.to_dict())
    return out


def main(argv: list[str] | None = None) -> int:
    _load_env()
    from agents.shared.slack_config import add_slack_cli_flags, cli_slack_from_args, slack_wanted

    parser = argparse.ArgumentParser(description="Analyze GradGPS timeline/SAP health")
    add_slack_cli_flags(parser)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)

    report = analyze(run_tests=not args.skip_tests)
    print(json.dumps(report.to_dict(), indent=2))
    if slack_wanted(cli_slack=cli_slack_from_args(args)):
        from agents.reporter.slack import post_analytics_report

        post_analytics_report(report, required=False)
    return 0 if report.metrics.get("pytest_ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
