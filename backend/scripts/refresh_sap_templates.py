"""
Regenerate every shipped Suggested Academic Plan template from today's bulletin
with the current scraper.

Why regenerate rather than patch:

  * STALE — 27 templates no longer matched PSU's current grid. ETI's still had
    "IST 110 / CYBER 100" where PSU now lists ETI 100, and no ETI 200 at all, so
    no ETI student was ever scheduled ETI 200.
  * MIS-TYPED — a codeless grid cell the classifier didn't recognise ("400-Level
    HIST Course", "Option Course", "Application Focus Selection") became a
    category-less gen-ed slot, and those are retired once a student's gen-eds
    are done: 1,137 major slots in 187 templates silently left the plans of
    students far enough along. scrape_sap._classify_placeholder now types them.

Every earlier template change is reproducible by the scraper: the git history
of sap_templates/ is scraper output (summer labels, family splits, 400-level
cells), the LA 83/LA 283 collapse (0a16a24, now collapse_renamed_duplicates),
Smeal's "BA 411 or a Business Breadth course" (6f6fea7, now scraped), and the
Forensic Chemistry corrections, which live in SUBPLAN_PROGRAMS and are
re-applied here. A template whose regeneration fails validation is left as is.

Usage (network, rate-limited; today's pages cached under --cache):
    python scripts/refresh_sap_templates.py --cache DIR            # dry run
    python scripts/refresh_sap_templates.py --cache DIR --write
"""

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

import scrape_sap as S                      # noqa: E402

UA = {"User-Agent": "GradGPS-SAPScraper/1.0 (educational use; mkrokosz06@gmail.com)"}


def regenerate(tpl: dict, html: str) -> dict:
    """`tpl` rebuilt from `html` (today's page), keeping its identity fields."""
    manual = next((s for s in S.SUBPLAN_PROGRAMS
                   if s["program_name"] == tpl["program_name"] and s["subplan"] == tpl.get("subplan")), None)
    if manual:
        grid, heading = S._grid_by_heading(html, manual["heading"])
        sems = S.parse_plangrid(grid)
        S._apply_corrections(sems, manual.get("corrections"))
        S._apply_supporting(sems, manual.get("supporting"))
    elif tpl.get("source_plan"):
        grid, _ = S._grid_by_heading(html, [tpl["source_plan"]])
        sems = S.parse_plangrid(grid)
    else:
        sems = S.parse_plangrid(html)
    S.collapse_renamed_duplicates(sems)
    return dict(tpl, semesters=sems, total_credits=round(sum(s["credits"] for s in sems), 1))


def main():
    import requests
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, help="directory for today's bulletin pages")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)

    def today(url):
        path = os.path.join(args.cache, re.sub(r"[^a-z0-9]+", "_", url.lower())[-120:] + ".html")
        if not os.path.exists(path):
            open(path, "w", encoding="utf-8").write(requests.get(url, headers=UA, timeout=30).text)
            time.sleep(1)
        return open(path, encoding="utf-8").read()

    counts = {"changed": 0, "unchanged": 0, "invalid, kept": 0, "error, kept": 0}
    for f in sorted(os.listdir(S._OUT_DIR)):
        path = os.path.join(S._OUT_DIR, f)
        tpl = json.load(open(path, encoding="utf-8"))
        try:
            new = regenerate(tpl, today(tpl["source"]))
        except Exception as e:                                          # noqa: BLE001
            counts["error, kept"] += 1
            print(f"  ERROR {f}: {e!r}"[:160])
            continue
        problems = S.validate_template(new) + S._sanity_problems(new)
        if problems:
            counts["invalid, kept"] += 1
            print(f"  INVALID {f}: {problems[:2]} - kept the old template")
            continue
        if new == tpl:
            counts["unchanged"] += 1
            continue
        counts["changed"] += 1
        if args.write:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(new, fh, indent=2, ensure_ascii=False)
    print(counts, "" if args.write else "| dry run - nothing written")


if __name__ == "__main__":
    main()
