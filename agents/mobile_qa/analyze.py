"""
Mobile QA — static checks for Expo layout / NativeWind / auth-dev pitfalls.

Usage:
  python -m agents.mobile_qa.analyze
  python -m agents.mobile_qa.analyze --slack
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.paths import MOBILE_ROOT, REPORTS_ROOT, ensure_work_dirs
from agents.shared.schemas import AnalyticsReport, Recommendation, load_dotenv_file, write_json


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def analyze() -> AnalyticsReport:
    ensure_work_dirs()
    tabs_layout = MOBILE_ROOT / "app" / "(tabs)" / "_layout.tsx"
    text = _read(tabs_layout)

    uses_tabs = "Tabs" in text and "from" in text
    # crude: Stack import used as the primary navigator in tabs layout
    stack_as_root = bool(re.search(r"from\s+['\"]expo-router['\"].*Stack|return\s*\(\s*<Stack", text, re.S))
    has_hidden_tab_bar = "display: \"none\"" in text or "display:'none'" in text or 'display: "none"' in text

    transcript_svc = _read(MOBILE_ROOT / "services" / "transcriptService.ts")
    has_official_ack = "isOfficialAckError" in transcript_svc

    metrics = {
        "tabs_layout_exists": tabs_layout.is_file(),
        "tabs_layout_references_Tabs": uses_tabs,
        "tabs_layout_looks_like_Stack_root": stack_as_root and "Tabs" not in text,
        "tab_bar_hidden": has_hidden_tab_bar,
        "isOfficialAckError_present": has_official_ack,
        "mobile_claude_md_exists": (MOBILE_ROOT / "CLAUDE.md").is_file(),
    }
    notes = [
        "(tabs) MUST remain <Tabs> with hidden tab bar — Stack breaks router.navigate() between siblings.",
        "NativeWind v4: prefer className over style objects for Tailwind classes.",
        "Expo SDK 54 — read https://docs.expo.dev/versions/v54.0.0/ before API changes.",
    ]
    recs: list[Recommendation] = []

    if not tabs_layout.is_file():
        recs.append(
            Recommendation(
                id="mobile-tabs-layout-missing",
                area="mobile",
                severity="critical",
                title="Missing mobile/app/(tabs)/_layout.tsx",
                rationale="Main app navigation lives under hidden Tabs.",
                suggested_owner="human",
                verify_steps=["Open mobile/app/(tabs)/_layout.tsx"],
                claude_md_refs=["Mobile / Navigation", "mobile/CLAUDE.md"],
            )
        )
    elif "Tabs" not in text:
        recs.append(
            Recommendation(
                id="mobile-tabs-converted-to-stack",
                area="mobile",
                severity="critical",
                title="(tabs)/_layout.tsx no longer uses Tabs",
                rationale="Converting to Stack breaks sibling router.navigate() — restore Tabs with hidden tab bar.",
                suggested_owner="human or implement_fix",
                verify_steps=["grep Tabs mobile/app/(tabs)/_layout.tsx"],
                claude_md_refs=["Mobile / Navigation"],
            )
        )

    if not has_official_ack:
        recs.append(
            Recommendation(
                id="mobile-official-ack-helper-missing",
                area="mobile",
                severity="high",
                title="transcriptService.isOfficialAckError missing",
                rationale="Official upload 409 consent flow depends on this helper.",
                suggested_owner="human",
                verify_steps=["Inspect mobile/services/transcriptService.ts"],
                claude_md_refs=["Official vs unofficial transcripts / Mobile"],
            )
        )

    out = AnalyticsReport(
        area="mobile",
        title="Mobile QA (static)",
        metrics=metrics,
        notes=notes,
        recommendations=recs,
    )
    write_json(REPORTS_ROOT / "mobile-qa-latest.json", out.to_dict())
    return out


def main(argv: list[str] | None = None) -> int:
    _load_env()
    from agents.shared.slack_config import add_slack_cli_flags, cli_slack_from_args, slack_wanted

    parser = argparse.ArgumentParser(description="Static QA for GradGPS mobile app")
    add_slack_cli_flags(parser)
    args = parser.parse_args(argv)

    report = analyze()
    print(json.dumps(report.to_dict(), indent=2))
    if slack_wanted(cli_slack=cli_slack_from_args(args)):
        from agents.reporter.slack import post_analytics_report

        post_analytics_report(report, required=False)

    critical = any(r.severity == "critical" for r in report.recommendations)
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
