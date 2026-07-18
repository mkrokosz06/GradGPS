"""
Local dispatcher — runs the specialist module for a DispatchPlan.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from agents.shared.schemas import DispatchPlan


def dispatch(plan: DispatchPlan, *, approve_id: str | None = None) -> dict[str, Any]:
    """Execute the planned agent. Returns a JSON-serializable result dict."""
    agent = plan.agent
    slack = plan.slack
    area = plan.area

    if agent == "test_runner":
        from agents.test_runner.run_tests import run_suite

        suite = "all" if area == "all" else str(area)
        if suite == "audit":
            report = run_suite("audit")
        else:
            report = run_suite(suite)
        result: dict[str, Any] = {"type": "TestReport", "report": report.to_dict()}

    elif agent == "audit_qa":
        from agents.audit_qa.analyze import analyze

        report = analyze(run_related_tests=True, with_seeded_user=False)
        result = {"type": "AnalyticsReport", "report": report.to_dict()}

    elif agent == "timeline_qa":
        from agents.timeline_qa.analyze import analyze

        report = analyze(run_tests=True)
        result = {"type": "AnalyticsReport", "report": report.to_dict()}

    elif agent == "transcript_qa":
        from agents.transcript_qa.analyze import analyze

        report = analyze(run_tests=True)
        result = {"type": "AnalyticsReport", "report": report.to_dict()}

    elif agent == "catalog_analyst":
        from agents.catalog_analyst.analyze import analyze

        report = analyze()
        result = {"type": "AnalyticsReport", "report": report.to_dict()}

    elif agent == "mobile_qa":
        from agents.mobile_qa.analyze import analyze

        report = analyze()
        result = {"type": "AnalyticsReport", "report": report.to_dict()}

    elif agent == "recommend":
        from agents.recommend.digest import collect, run_all_analyzers

        run_all_analyzers(skip_tests=False)
        recs = collect(None if area == "all" else str(area))
        result = {
            "type": "Recommendations",
            "count": len(recs),
            "recommendations": [r.to_dict() for r in recs],
        }

    elif agent == "implement_fix":
        from agents.implement_fix.apply import apply_recommendation

        return apply_recommendation(approve_id, slack=slack)

    else:
        raise SystemExit(f"Unknown agent: {agent}")

    if slack:
        from agents.reporter.slack import post_dispatch_result

        post_dispatch_result(result, required=False)

    return result


def dump(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2))
