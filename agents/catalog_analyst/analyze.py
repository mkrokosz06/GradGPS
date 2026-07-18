"""
Catalog analyst — inventory seed/patch/gen-ed/SAP artifacts and recommend scrape/patch work.

Does not invent course lists. Never recommends running seed_gen_ed.py for domain pools.

Usage:
  python -m agents.catalog_analyst.analyze
  python -m agents.catalog_analyst.analyze --slack
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

from agents.paths import BACKEND_ROOT, REPORTS_ROOT, ensure_work_dirs
from agents.shared.schemas import AnalyticsReport, Recommendation, load_dotenv_file, write_json


def _load_env() -> None:
    load_dotenv_file(_REPO / "agents" / "runtime" / ".env")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def analyze() -> AnalyticsReport:
    ensure_work_dirs()
    scripts = BACKEND_ROOT / "scripts"
    seed_matthew = scripts / "seed_matthew.py"
    gen_ed_json = scripts / "gen_ed_courses.json"
    rebuild = scripts / "rebuild_gen_ed.py"
    seed_gen_ed = scripts / "seed_gen_ed.py"

    seed_text = _read(seed_matthew)
    pair_literals = re.findall(r'Decimal\("(\d+)"\)', seed_text)
    pair_ids = sorted({int(x) for x in pair_literals})

    has_phys = "def patch_phys_alternatives" in seed_text
    has_math = "patch_math" in seed_text or "MATH 250" in seed_text
    has_eti_pairs = "PAIRS" in seed_text and "580" in seed_text

    gen_ed_count = 0
    if gen_ed_json.is_file():
        try:
            data = json.loads(gen_ed_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                gen_ed_count = sum(len(v) if isinstance(v, list) else 1 for v in data.values())
            elif isinstance(data, list):
                gen_ed_count = len(data)
        except json.JSONDecodeError:
            gen_ed_count = -1

    sap_templates = sorted(p.name for p in (BACKEND_ROOT / "sap_templates").glob("*.json"))

    metrics = {
        "seed_matthew_exists": seed_matthew.is_file(),
        "rebuild_gen_ed_exists": rebuild.is_file(),
        "seed_gen_ed_exists": seed_gen_ed.is_file(),
        "gen_ed_courses_json_exists": gen_ed_json.is_file(),
        "gen_ed_courses_json_entries": gen_ed_count,
        "pair_id_literals_in_seed_matthew": pair_ids,
        "has_patch_phys_alternatives": has_phys,
        "has_math_pair_logic": has_math,
        "has_eti_pairs": has_eti_pairs,
        "sap_templates": sap_templates,
    }

    notes = [
        "Authoritative gen-ed domain pools: scripts/gen_ed_courses.json via rebuild_gen_ed.py.",
        "Do NOT run seed_gen_ed.py for domain pools — fabricated titles/attributes; Communication groups only.",
        "ETI pair IDs 580–583; PHYS 211/250 from 600+; MATH 250/251 from 700+.",
        "After Docker restart: setup_tables → load_catalog → rebuild_gen_ed → seed_matthew.",
    ]
    recs: list[Recommendation] = []

    if not gen_ed_json.is_file():
        recs.append(
            Recommendation(
                id="catalog-missing-gen-ed-json",
                area="catalog",
                severity="critical",
                title="Missing scripts/gen_ed_courses.json",
                rationale="rebuild_gen_ed.py expects scraped bulletin data in gen_ed_courses.json.",
                suggested_owner="human",
                verify_steps=[
                    "cd backend && python scripts/scrape_gen_ed_courses.py",
                    "cd backend && python scripts/rebuild_gen_ed.py",
                ],
                claude_md_refs=["Running the project / Gen ed data"],
            )
        )

    if seed_matthew.is_file() and not has_phys:
        recs.append(
            Recommendation(
                id="catalog-phys-patch-missing",
                area="catalog",
                severity="high",
                title="PHYS 211/250 patch function missing from seed_matthew.py",
                rationale="CLAUDE.md documents patch_phys_alternatives for 32+ programs.",
                suggested_owner="human",
                verify_steps=["Inspect backend/scripts/seed_matthew.py for patch_phys_alternatives"],
                claude_md_refs=["Catalog patches / PHYS 211 / PHYS 250"],
            )
        )

    if len(sap_templates) <= 2:
        recs.append(
            Recommendation(
                id="catalog-sap-template-coverage",
                area="catalog",
                severity="low",
                title="SAP templates still limited (catalog/timeline joint work)",
                rationale="Coordinate with TimelineQA: scrape_sap.py --check-catalog for new UP majors.",
                suggested_owner="human",
                verify_steps=["cd backend && python scripts/scrape_sap.py --dry-run --check-catalog"],
                claude_md_refs=["Suggested Academic Plans", "docs/timeline-sap-hybrid.md"],
            )
        )

    # Reminder recommendation always present as info
    recs.append(
        Recommendation(
            id="catalog-never-fabricate-gen-ed",
            area="catalog",
            severity="info",
            title="Never hand-author gen-ed domain pools",
            rationale="Use scrape_gen_ed_courses.py → rebuild_gen_ed.py. seed_gen_ed.py is Communication-only.",
            suggested_owner="human",
            verify_steps=["Read CLAUDE.md Gen ed data section"],
            claude_md_refs=["Running the project / Gen ed data"],
        )
    )

    out = AnalyticsReport(
        area="catalog",
        title="Catalog / seed / gen-ed analytics",
        metrics=metrics,
        notes=notes,
        recommendations=recs,
    )
    write_json(REPORTS_ROOT / "catalog-analyst-latest.json", out.to_dict())
    return out


def main(argv: list[str] | None = None) -> int:
    _load_env()
    from agents.shared.slack_config import add_slack_cli_flags, cli_slack_from_args, slack_wanted

    parser = argparse.ArgumentParser(description="Analyze GradGPS catalog/seed artifacts")
    add_slack_cli_flags(parser)
    args = parser.parse_args(argv)

    report = analyze()
    print(json.dumps(report.to_dict(), indent=2))
    if slack_wanted(cli_slack=cli_slack_from_args(args)):
        from agents.reporter.slack import post_analytics_report

        post_analytics_report(report, required=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
