"""
Scrape every University Park degree program's "Entrance to Major" section into
`backend/entrance_data/entrance_requirements.json`.

Why a bundled JSON rather than DynamoDB rows — the same reasoning as
`credential_requirements.json`: prod IAM is per-table scoped so a new table needs
an infra change first, a bundled file needs no prod seeding run on a data
refresh, and it diffs in git so a re-scrape is a reviewable PR.

Why not requirement rows at all: entrance to major is a GATE over courses the
major already requires (see entrance_parse's module docstring). Storing them as
requirements would double-count the credits and schedule the course twice.

    cd backend
    python scripts/scrape_entrance_to_major.py            # full scrape
    python scripts/scrape_entrance_to_major.py --report   # reprint file stats
    python scripts/scrape_entrance_to_major.py --limit 20 # first N programs

`--report` prints how many programs have a gate and how many of their courses
are already known to the catalog. A PSU page edit that breaks a parse shows up
as a drop in those numbers rather than as a wrong gate in a student's audit.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from entrance_parse import extract_section, parse_entrance_section
from routers.programs import is_degree_program, is_up_program

import scrape_psu

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "entrance_data")
OUT_PATH = os.path.join(OUT_DIR, "entrance_requirements.json")

HEADERS = {
    "User-Agent": "GradGPS-CatalogScraper/1.0 (educational use; mkrokosz06@gmail.com)"
}


def fetch(url: str, tries: int = 3) -> str | None:
    for attempt in range(tries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.ok:
                return resp.text
        except requests.RequestException:
            pass
        time.sleep(1 + attempt)
    return None


def report(data: dict) -> None:
    progs = data.get("programs", {})
    with_gate = [p for p in progs.values() if p.get("groups")]
    unmodelled = [p for p in progs.values() if p.get("has_unmodelled")]
    gpa = [p for p in progs.values() if p.get("gpa_min")]
    standing = [p for p in progs.values() if p.get("semester_standing")]
    # A group is a list of BRANCHES, each a list of codes — "ACCTG 211 or
    # (ACCTG 201 and ACCTG 202)" is one group, three branches, four codes.
    courses = {c for p in progs.values() for g in p.get("groups", [])
               for branch in g for c in branch}
    branches = sum(len(g) for p in progs.values() for g in p.get("groups", []))
    compound = sum(1 for p in progs.values() for g in p.get("groups", [])
                   for b in g if len(b) > 1)
    print("=" * 66)
    print(f"  Programs with an Entrance to Major section : {len(progs)}")
    print(f"  ... naming specific courses                : {len(with_gate)}")
    print(f"  ... stating a GPA floor                    : {len(gpa)}")
    print(f"  ... stating a semester standing            : {len(standing)}")
    print(f"  ... carrying a condition we cannot check   : {len(unmodelled)}")
    print(f"  Distinct gate courses                      : {len(courses)}")
    print(f"  Alternative branches across all gates      : {branches}")
    print(f"  ... of which are compound (A and B)        : {compound}")
    print("=" * 66)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", action="store_true",
                    help="reprint stats from the existing file and exit")
    args = ap.parse_args(argv)

    if args.report:
        with open(OUT_PATH, encoding="utf-8") as fh:
            report(json.load(fh))
        return 0

    programs = scrape_psu.get_all_programs()
    if not programs:
        print("No programs found.")
        return 1

    # The program index has no degree attribute, so UP-scope here and let the
    # requirements catalog be the authority on what is a degree program.
    programs = [p for p in programs if is_up_program(p["name"])
                and is_degree_program(p["name"], set())]
    if args.limit:
        programs = programs[: args.limit]
    print(f"Scanning {len(programs)} University Park degree programs...\n")

    out: dict[str, dict] = {}
    no_section = 0
    for i, prog in enumerate(programs, 1):
        html_text = fetch(prog["url"])
        label = prog["name"][:58]
        if not html_text:
            print(f"[{i:>3}/{len(programs)}] {label:<60} FETCH FAILED")
            continue
        section = extract_section(html_text)
        if section is None:
            no_section += 1
            print(f"[{i:>3}/{len(programs)}] {label:<60} no section")
            continue
        spec = parse_entrance_section(section)
        spec["source_url"] = prog["url"]
        out[prog["name"]] = spec
        flag = "!" if spec["has_unmodelled"] else " "
        print(f"[{i:>3}/{len(programs)}] {label:<60} "
              f"{len(spec['groups'])} groups gpa={spec['gpa_min']} {flag}")

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "source": "https://bulletins.psu.edu/undergraduate/",
        "scraped_programs": len(out),
        "programs": out,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
    print(f"\nWrote {OUT_PATH}")
    print(f"{no_section} programs have no Entrance to Major section.")
    report(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
