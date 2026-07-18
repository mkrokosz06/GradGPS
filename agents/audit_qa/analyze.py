"""
Audit QA — measure degree-audit test coverage and recommend engine vs catalog work.

Calls run_audit / run_gen_ed_audit only inside this harness (never via HTTP).

Usage:
  python -m agents.audit_qa.analyze
  python -m agents.audit_qa.analyze --slack
  python -m agents.audit_qa.analyze --with-seeded-user
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.paths import BACKEND_ROOT, REPORTS_ROOT, TESTS_ROOT, ensure_work_dirs
from agents.shared.schemas import AnalyticsReport, Recommendation, load_dotenv_file, write_json
from agents.test_runner.run_tests import run_suite


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")
    load_dotenv_file(_REPO / "backend" / ".env")


def _audit_test_file() -> Path:
    return TESTS_ROOT / "test_audit_engine.py"


def _recommendations_for_gaps() -> list[Recommendation]:
    recs: list[Recommendation] = []
    if not _audit_test_file().is_file():
        recs.append(
            Recommendation(
                id="audit-missing-pytest",
                area="audit",
                severity="high",
                title="Add backend/tests/test_audit_engine.py",
                rationale=(
                    "There is no dedicated pytest module for run_audit / run_gen_ed_audit. "
                    "Timeline and transcript have suites; audit regressions (choose_one pairs, "
                    "choose_credits thresholds, WAC writing_intensive, gen-ed exclusivity) are unguarded."
                ),
                suggested_owner="human or implement_fix",
                verify_steps=[
                    "cd backend && python -m pytest tests/test_audit_engine.py -v",
                    "Cover: choose_one pair_status, choose_credits single slot, _eval_writing_intensive, multi_category",
                ],
                claude_md_refs=["Key decisions & known quirks / Audit engine", "Gen ed / WAC"],
            )
        )
    else:
        recs.append(
            Recommendation(
                id="audit-expand-fixture-coverage",
                area="audit",
                severity="low",
                title="Expand audit fixtures beyond synthetic rows",
                rationale=(
                    "test_audit_engine.py covers core behaviors with synthetic rows. "
                    "Next: golden fixtures from matthew-test-001 / known ETI pairs when DynamoDB is seeded."
                ),
                suggested_owner="human",
                verify_steps=[
                    "cd backend && python -m pytest tests/test_audit_engine.py -v",
                    "python -m agents.audit_qa.analyze --with-seeded-user",
                ],
                claude_md_refs=["Test user", "Key decisions & known quirks / Audit engine"],
            )
        )
    return recs


def _try_seeded_matthew_audit() -> tuple[dict, list[str]]:
    """If DynamoDB local + seed are up, run audit for matthew-test-001."""
    notes: list[str] = []
    # Ensure backend/.env is loaded before db.py reads DYNAMODB_ENDPOINT
    load_dotenv_file(_REPO / "backend" / ".env")
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from boto3.dynamodb.conditions import Key  # type: ignore
        from db import requirements_table, transcript_table, users_table  # type: ignore
        from audit_engine import run_audit, run_gen_ed_audit  # type: ignore
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Could not import backend modules: {exc}")
        return {}, notes

    try:
        user = users_table.get_item(Key={"user_id": "matthew-test-001"}).get("Item")
        if not user:
            notes.append(
                "User matthew-test-001 not found. Run: "
                "python scripts/setup_tables.py && python scripts/load_catalog.py && "
                "python scripts/rebuild_gen_ed.py && python scripts/seed_matthew.py"
            )
            return {}, notes

        major = user.get("major")
        if not major:
            notes.append("matthew-test-001 has no major set")
            return {}, notes

        major_rows = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(major)
        ).get("Items", [])
        gen_ed_rows = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq("__GEN_ED__")
        ).get("Items", [])
        transcript = transcript_table.query(
            KeyConditionExpression=Key("user_id").eq("matthew-test-001")
        ).get("Items", [])

        if not major_rows:
            notes.append(
                f"No requirement rows for major {major!r}. "
                "PSU_Major_Requirements.xlsx is missing or load_catalog.py was not run. "
                "Place the xlsx at repo root and re-run load_catalog.py + seed_matthew.py."
            )

        major_audit = run_audit(major_rows, transcript) if major_rows else None
        gen_ed_audit = run_gen_ed_audit(gen_ed_rows, transcript) if gen_ed_rows else None

        summary: dict = {
            "user_id": "matthew-test-001",
            "major": major,
            "transcript_courses": len(transcript),
            "major_requirement_rows": len(major_rows),
            "gen_ed_requirement_rows": len(gen_ed_rows),
        }
        if isinstance(major_audit, dict):
            groups = major_audit.get("groups") or []
            summary["major_groups"] = len(groups)
            summary["major_done"] = major_audit.get("done")
            summary["major_missing"] = major_audit.get("missing")
            summary["major_in_progress"] = major_audit.get("in_progress")
            statuses: dict[str, int] = {}
            for g in groups:
                if not isinstance(g, dict):
                    continue
                st = "satisfied" if g.get("satisfied") else "unsatisfied"
                statuses[st] = statuses.get(st, 0) + 1
            summary["major_group_satisfied_counts"] = statuses
        if isinstance(gen_ed_audit, dict):
            summary["gen_ed_groups"] = len(gen_ed_audit.get("groups") or [])
            summary["gen_ed_done"] = gen_ed_audit.get("done")
            summary["gen_ed_missing"] = gen_ed_audit.get("missing")
            summary["gen_ed_credits_earned"] = gen_ed_audit.get("credits_earned")

        if major_rows:
            notes.append(
                f"Seeded audit OK for matthew-test-001 "
                f"({summary['transcript_courses']} transcript courses, "
                f"{summary['major_requirement_rows']} major rows)."
            )
        elif gen_ed_rows:
            notes.append(
                f"Gen-ed audit OK for matthew-test-001 "
                f"({summary['transcript_courses']} courses, {len(gen_ed_rows)} gen-ed rows); "
                "major catalog still empty."
            )
        return summary, notes
    except Exception as exc:  # noqa: BLE001
        notes.append(
            f"Seeded audit failed (is Docker DynamoDB up and seeded?): {exc}"
        )
        return {}, notes


def analyze(*, run_related_tests: bool = True, with_seeded_user: bool = False) -> AnalyticsReport:
    ensure_work_dirs()
    metrics: dict = {
        "audit_test_file_exists": _audit_test_file().is_file(),
        "audit_test_path": str(_audit_test_file()),
    }
    notes: list[str] = []
    recs = _recommendations_for_gaps()

    if run_related_tests:
        # No audit-only suite — run catalog/programs + note; prefer not to run full suite every time
        # Run programs_scope as a cheap smoke; full suite via test_runner
        try:
            programs_report = run_suite("catalog")
            metrics["programs_scope_pytest_ok"] = programs_report.ok
            metrics["programs_scope_passed"] = programs_report.passed
            metrics["programs_scope_failed"] = programs_report.failed
            if not programs_report.ok:
                notes.append(f"programs_scope tests failed — see {programs_report.log_path}")
                recs.append(
                    Recommendation(
                        id="audit-programs-scope-fail",
                        area="audit",
                        severity="high",
                        title="Fix failing programs_scope tests before audit work",
                        rationale="UP program scoping failures can mis-route SAP and catalog assumptions.",
                        suggested_owner="human",
                        verify_steps=["cd backend && python -m pytest tests/test_programs_scope.py -v"],
                        claude_md_refs=["Suggested Academic Plans / University Park scoping"],
                    )
                )
        except SystemExit as exc:
            notes.append(str(exc))

    if with_seeded_user:
        seeded_summary, seeded_notes = _try_seeded_matthew_audit()
        notes.extend(seeded_notes)
        if seeded_summary:
            metrics["seeded_matthew_audit"] = seeded_summary
            if seeded_summary.get("major_requirement_rows", 0) == 0:
                recs.append(
                    Recommendation(
                        id="catalog-missing-xlsx",
                        area="catalog",
                        severity="critical",
                        title="Rebuild PSU_Major_Requirements.xlsx via scrape_psu.py",
                        rationale=(
                            "Major catalog is empty or incomplete. Regenerate from the PSU bulletin "
                            "with backend/scripts/scrape_psu.py (not hand-authored rows)."
                        ),
                        suggested_owner="human",
                        verify_steps=[
                            "cd backend && python scripts/scrape_psu.py",
                            "cd backend && python scripts/load_catalog.py && python scripts/seed_matthew.py",
                            "python -m agents.audit_qa.analyze --with-seeded-user",
                        ],
                        claude_md_refs=["Running the project / Seed the database", "README scrape_psu.py"],
                    )
                )

    # Static code reminders from CLAUDE.md
    notes.append(
        "Manual checklist: choose_one uses pair_group_id; choose_credits must stay one timeline slot; "
        "WAC is group_type=writing_intensive evaluated via is_writing."
    )

    report = AnalyticsReport(
        area="audit",
        title="Degree audit QA",
        metrics=metrics,
        notes=notes,
        recommendations=recs,
    )
    stamp_path = REPORTS_ROOT / "audit-qa-latest.json"
    write_json(stamp_path, report.to_dict())
    return report


def main(argv: list[str] | None = None) -> int:
    _load_env()
    from agents.shared.slack_config import add_slack_cli_flags, cli_slack_from_args, slack_wanted

    parser = argparse.ArgumentParser(description="Analyze GradGPS audit test coverage")
    add_slack_cli_flags(parser)
    parser.add_argument(
        "--with-seeded-user",
        action="store_true",
        help="If DynamoDB is seeded, run run_audit for matthew-test-001",
    )
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)

    report = analyze(run_related_tests=not args.skip_tests, with_seeded_user=args.with_seeded_user)
    print(json.dumps(report.to_dict(), indent=2))

    if slack_wanted(cli_slack=cli_slack_from_args(args)):
        from agents.reporter.slack import post_analytics_report

        post_analytics_report(report, required=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
