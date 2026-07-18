"""Map natural-language / CLI requests to GradGPS specialist agents."""

from __future__ import annotations

import re
from typing import Literal

from agents.shared.schemas import Area, DispatchPlan, Intent

AreaOrAll = Area | Literal["all"]

# (keywords, area) — first match wins within an intent
_AREA_KEYWORDS: list[tuple[tuple[str, ...], Area]] = [
    (("audit", "choose_one", "choose_credits", "gen ed", "gen_ed", "wac", "writing intensive", "pair_group"), "audit"),
    (("timeline", "packing", "sap", "reflow", "semester", "credit band"), "timeline"),
    (("transcript", "official", "pdf", "watermark", "acknowledge_official", "409"), "transcript"),
    (("catalog", "seed_matthew", "rebuild_gen_ed", "scrape", "pair id", "requirements"), "catalog"),
    (("mobile", "expo", "nativewind", "navheader", "onboarding", "tabs"), "mobile"),
    (("auth", "oidc", "google", "apple", "securestore", "auth_dev_bypass"), "auth"),
]

_INTENT_KEYWORDS: list[tuple[tuple[str, ...], Intent]] = [
    (("implement", "fix", "patch", "pr for", "apply recommendation"), "implement_fix"),
    (("recommend", "recommendation", "backlog", "prioritize"), "recommend"),
    (("analyze", "analytics", "coverage", "metrics", "digest", "inspect"), "analyze"),
    (("test", "pytest", "run tests", "suite"), "test"),
]

_AGENT_BY_INTENT_AREA: dict[tuple[Intent, str], str] = {
    ("test", "all"): "test_runner",
    ("test", "audit"): "test_runner",
    ("test", "timeline"): "test_runner",
    ("test", "transcript"): "test_runner",
    ("test", "catalog"): "test_runner",
    ("test", "mobile"): "mobile_qa",
    ("test", "auth"): "test_runner",
    ("analyze", "audit"): "audit_qa",
    ("analyze", "timeline"): "timeline_qa",
    ("analyze", "transcript"): "transcript_qa",
    ("analyze", "catalog"): "catalog_analyst",
    ("analyze", "mobile"): "mobile_qa",
    ("analyze", "auth"): "mobile_qa",  # auth checks live with human; mobile_qa flags UI auth gaps
    ("analyze", "all"): "recommend",
    ("recommend", "all"): "recommend",
    ("recommend", "audit"): "recommend",
    ("recommend", "timeline"): "recommend",
    ("recommend", "transcript"): "recommend",
    ("recommend", "catalog"): "recommend",
    ("recommend", "mobile"): "recommend",
    ("recommend", "auth"): "recommend",
    ("implement_fix", "all"): "implement_fix",
    ("implement_fix", "audit"): "implement_fix",
    ("implement_fix", "timeline"): "implement_fix",
    ("implement_fix", "transcript"): "implement_fix",
    ("implement_fix", "catalog"): "implement_fix",
    ("implement_fix", "mobile"): "implement_fix",
    ("implement_fix", "auth"): "implement_fix",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def detect_intent(text: str, explicit: Intent | None = None) -> Intent:
    if explicit:
        return explicit
    n = _normalize(text)
    for keys, intent in _INTENT_KEYWORDS:
        if any(k in n for k in keys):
            return intent
    # Default: analyze if area-ish, else test
    if any(any(k in n for k in keys) for keys, _ in _AREA_KEYWORDS):
        return "analyze"
    return "test"


def detect_area(text: str, explicit: AreaOrAll | None = None) -> AreaOrAll:
    if explicit:
        return explicit
    n = _normalize(text)
    if n in {"all", "everything", "full"} or "all tests" in n or "entire" in n:
        return "all"
    for keys, area in _AREA_KEYWORDS:
        if any(k in n for k in keys):
            return area
    if detect_intent(text) == "test":
        return "all"
    return "all"


def route(
    raw_request: str,
    *,
    intent: Intent | None = None,
    area: AreaOrAll | None = None,
    slack: bool = True,
) -> DispatchPlan:
    resolved_intent = detect_intent(raw_request, intent)
    resolved_area = detect_area(raw_request, area)

    # Auth implement/analyze → still route but reason warns human-gated
    agent = _AGENT_BY_INTENT_AREA.get((resolved_intent, resolved_area))
    if agent is None:
        agent = "test_runner" if resolved_intent == "test" else "recommend"

    reason_parts = [f"intent={resolved_intent}", f"area={resolved_area}"]
    if resolved_area == "auth":
        reason_parts.append("auth is human-gated for product changes; agents only analyze/test")
    if resolved_intent == "implement_fix":
        reason_parts.append("requires --approve <recommendation_id>")

    return DispatchPlan(
        intent=resolved_intent,
        area=resolved_area,  # type: ignore[arg-type]
        agent=agent,
        reason="; ".join(reason_parts),
        raw_request=raw_request,
        slack=slack,
    )


# Pytest path fragments relative to backend/
SUITE_PATHS: dict[str, list[str]] = {
    "all": ["tests"],
    "audit": ["tests/test_audit_engine.py"],
    "timeline": [
        "tests/test_timeline_packing.py",
        "tests/test_sap_schedule.py",
        "tests/test_plan_templates.py",
        "tests/test_scrape_sap.py",
    ],
    "transcript": ["tests/test_official_detector.py"],
    "catalog": ["tests/test_programs_scope.py"],
    "mobile": [],  # handled by mobile_qa
    "auth": [],
}
