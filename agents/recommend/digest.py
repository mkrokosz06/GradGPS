"""
Aggregate latest analyst reports into a ranked recommendation digest.

Usage:
  python -m agents.recommend.digest
  python -m agents.recommend.digest --run-all --slack
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.paths import REPORTS_ROOT, ensure_work_dirs
from agents.shared.schemas import Recommendation, load_dotenv_file, write_json

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

_LATEST_FILES = [
    "audit-qa-latest.json",
    "timeline-qa-latest.json",
    "transcript-qa-latest.json",
    "catalog-analyst-latest.json",
    "mobile-qa-latest.json",
]


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")


def _recs_from_file(path: Path) -> list[Recommendation]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[Recommendation] = []
    for r in data.get("recommendations", []):
        out.append(
            Recommendation(
                id=r["id"],
                area=r["area"],
                severity=r["severity"],
                title=r["title"],
                rationale=r["rationale"],
                suggested_owner=r.get("suggested_owner", "human"),
                verify_steps=r.get("verify_steps", []),
                claude_md_refs=r.get("claude_md_refs", []),
                created_at=r.get("created_at", ""),
            )
        )
    return out


def collect(area_filter: str | None = None) -> list[Recommendation]:
    ensure_work_dirs()
    recs: list[Recommendation] = []
    for name in _LATEST_FILES:
        recs.extend(_recs_from_file(REPORTS_ROOT / name))
    if area_filter and area_filter != "all":
        recs = [r for r in recs if r.area == area_filter]
    # Dedupe by id, keep highest severity
    by_id: dict[str, Recommendation] = {}
    for r in recs:
        prev = by_id.get(r.id)
        if prev is None or _SEVERITY_ORDER[r.severity] < _SEVERITY_ORDER[prev.severity]:
            by_id[r.id] = r
    ranked = sorted(by_id.values(), key=lambda r: (_SEVERITY_ORDER[r.severity], r.area, r.id))
    return ranked


def run_all_analyzers(*, skip_tests: bool = False) -> None:
    from agents.audit_qa.analyze import analyze as audit_analyze
    from agents.catalog_analyst.analyze import analyze as catalog_analyze
    from agents.mobile_qa.analyze import analyze as mobile_analyze
    from agents.timeline_qa.analyze import analyze as timeline_analyze
    from agents.transcript_qa.analyze import analyze as transcript_analyze

    audit_analyze(run_related_tests=not skip_tests, with_seeded_user=False)
    timeline_analyze(run_tests=not skip_tests)
    transcript_analyze(run_tests=not skip_tests)
    catalog_analyze()
    mobile_analyze()


def main(argv: list[str] | None = None) -> int:
    _load_env()
    from agents.shared.slack_config import add_slack_cli_flags, cli_slack_from_args, slack_wanted

    parser = argparse.ArgumentParser(description="Rank GradGPS agent recommendations")
    parser.add_argument("--run-all", action="store_true", help="Refresh all analyst reports first")
    parser.add_argument("--skip-tests", action="store_true", help="With --run-all, skip pytest")
    parser.add_argument("--area", default="all", help="Filter by area")
    add_slack_cli_flags(parser)
    args = parser.parse_args(argv)

    if args.run_all:
        run_all_analyzers(skip_tests=args.skip_tests)

    recs = collect(None if args.area == "all" else args.area)
    payload = {"count": len(recs), "recommendations": [r.to_dict() for r in recs]}
    write_json(REPORTS_ROOT / "recommendations-latest.json", payload)
    print(json.dumps(payload, indent=2))

    if slack_wanted(cli_slack=cli_slack_from_args(args)):
        from agents.reporter.slack import post_recommendations

        post_recommendations(recs, title="Ranked recommendations", required=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
