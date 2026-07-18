"""
Transcript QA — run official-detector tests and flag fixture / consent gaps.

Usage:
  python -m agents.transcript_qa.analyze
  python -m agents.transcript_qa.analyze --slack
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.paths import REPORTS_ROOT, ensure_work_dirs
from agents.shared.schemas import AnalyticsReport, Recommendation, load_dotenv_file, write_json
from agents.test_runner.run_tests import run_suite


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")
    load_dotenv_file(_REPO / "backend" / ".env")


def analyze(*, run_tests: bool = True) -> AnalyticsReport:
    ensure_work_dirs()
    sample = os.environ.get("OFFICIAL_SAMPLE_PDF")
    metrics: dict = {
        "official_sample_pdf_set": bool(sample),
        "official_sample_pdf_exists": bool(sample and Path(sample).is_file()),
        "official_detect_env": os.environ.get("OFFICIAL_DETECT", "<unset=shadow mode>"),
    }
    notes = [
        "Official detection: /ByteRange + adbe.pkcs7 (+4); do not test spaced /Type /Sig.",
        "Watermark drop is by font size (_WATERMARK_MIN_SIZE); real text ~6–9pt.",
        "OFFICIAL_DETECT unset = shadow mode (no 409). Set OFFICIAL_DETECT=1 to enforce consent.",
        "Mobile: transcriptService.isOfficialAckError; guard typeof detail === 'string'.",
    ]
    recs: list[Recommendation] = []

    if not metrics["official_sample_pdf_exists"]:
        recs.append(
            Recommendation(
                id="transcript-more-official-samples",
                area="transcript",
                severity="medium",
                title="Add more real official transcript samples for e2e tests",
                rationale=(
                    "Official parser is tuned from a single sample. Set OFFICIAL_SAMPLE_PDF to exercise "
                    "the end-to-end path in test_official_detector.py; validate before trusting broadly."
                ),
                suggested_owner="human",
                verify_steps=[
                    "set OFFICIAL_SAMPLE_PDF=path/to/official.pdf",
                    "cd backend && python -m pytest tests/test_official_detector.py -v",
                ],
                claude_md_refs=["Official vs unofficial transcripts", "docs/official-transcript-handling.md"],
            )
        )

    if run_tests:
        report = run_suite("transcript")
        metrics["pytest_ok"] = report.ok
        metrics["pytest_passed"] = report.passed
        metrics["pytest_failed"] = report.failed
        metrics["pytest_log"] = report.log_path
        if not report.ok:
            recs.append(
                Recommendation(
                    id="transcript-pytest-failing",
                    area="transcript",
                    severity="critical",
                    title="Fix failing official transcript tests",
                    rationale=f"Failures: {', '.join(report.failing_nodeids) or 'see log'}",
                    suggested_owner="human or implement_fix",
                    verify_steps=["cd backend && python -m pytest tests/test_official_detector.py -v"],
                    claude_md_refs=["Official vs unofficial transcripts"],
                )
            )
        else:
            notes.append(f"Official detector pytest green ({report.passed} passed).")

    out = AnalyticsReport(
        area="transcript",
        title="Transcript / official-detect QA",
        metrics=metrics,
        notes=notes,
        recommendations=recs,
    )
    write_json(REPORTS_ROOT / "transcript-qa-latest.json", out.to_dict())
    return out


def main(argv: list[str] | None = None) -> int:
    _load_env()
    from agents.shared.slack_config import add_slack_cli_flags, cli_slack_from_args, slack_wanted

    parser = argparse.ArgumentParser(description="Analyze GradGPS transcript parsing health")
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
