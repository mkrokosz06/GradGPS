"""
GradGPS central orchestrator — route a request to the right local specialist.

Usage:
  python -m agents.orchestrator.run "run timeline tests"
  python -m agents.orchestrator.run "analyze audit" --slack
  python -m agents.orchestrator.run "recommendations" --intent recommend
  python -m agents.orchestrator.run "implement fix" --approve audit-missing-pytest

With SLACK_ENABLED=1 in agents/runtime/.env, Slack posting is on by default.

Never imports into FastAPI. Dev-team only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.runtime.local import dispatch, dump
from agents.shared.routing import route
from agents.shared.slack_config import (
    add_slack_cli_flags,
    cli_slack_from_args,
    load_agent_env,
    slack_wanted,
)


def main(argv: list[str] | None = None) -> int:
    load_agent_env()
    parser = argparse.ArgumentParser(description="Orchestrate GradGPS local dev agents")
    parser.add_argument("request", nargs="?", default="", help="Natural language request")
    parser.add_argument(
        "--intent",
        choices=["test", "analyze", "recommend", "implement_fix"],
        help="Override intent detection",
    )
    parser.add_argument(
        "--area",
        choices=["audit", "timeline", "transcript", "catalog", "mobile", "auth", "all"],
        help="Override area detection",
    )
    add_slack_cli_flags(parser)
    parser.add_argument("--no-slack-claim", action="store_true", help="Skip 'claimed' Slack message")
    parser.add_argument("--approve", help="Recommendation id (required for implement_fix)")
    parser.add_argument("--dry-run", action="store_true", help="Print DispatchPlan only")
    args = parser.parse_args(argv)

    if not args.request and not args.intent:
        parser.error("Provide a request string and/or --intent")

    use_slack = slack_wanted(cli_slack=cli_slack_from_args(args))

    plan = route(
        args.request or f"{args.intent} {args.area or 'all'}",
        intent=args.intent,  # type: ignore[arg-type]
        area=args.area,  # type: ignore[arg-type]
        slack=use_slack,
    )

    print(json.dumps({"dispatch_plan": plan.to_dict()}, indent=2))

    if args.dry_run:
        return 0

    if use_slack and not args.no_slack_claim:
        from agents.reporter.slack import post_claimed

        post_claimed(plan.agent, plan.raw_request, plan.reason, required=False)

    result = dispatch(plan, approve_id=args.approve)
    dump(result)

    if result.get("type") == "TestReport":
        return 0 if result["report"].get("exit_code", 1) == 0 else 1
    if result.get("type") == "AnalyticsReport":
        report = result["report"]
        if report.get("metrics", {}).get("pytest_ok") is False:
            return 1
        if any(r.get("severity") == "critical" for r in report.get("recommendations", [])):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
