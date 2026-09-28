"""
Scrape which degree programs the PSU bulletin says are NOT offered at University
Park into `backend/program_data/non_up_programs.json`.

Why this exists
---------------
`is_up_program()` used to decide University Park scope from the program name alone,
dropping names with a non-UP campus parenthetical ("Accounting, B.S. (Capital)").
But most branch-campus programs carry no parenthetical at all — "Law and Society,
B.A." (Abington), "Engineering, B.S." (Behrend), "Social Work, B.S.W." (several
Commonwealth campuses) — so 41 of them leaked into the major picker, and a UP
student could build a plan around a major they cannot enrol in.

The bulletin's program index (bulletins.psu.edu/programs/) tags every entry with its
campuses as isotope filter classes; `filter_87` is University Park. So read that.

This stays a DENYLIST on purpose: a program the file doesn't mention is kept, so a
new major added by a catalog re-scrape still shows up before this file is refreshed.
Only programs the bulletin positively lists *without* University Park are dropped.

    cd backend
    python scripts/scrape_program_campuses.py            # rewrite the file
    python scripts/scrape_program_campuses.py --dry-run  # print counts only
"""

import argparse
import html
import json
import os
import re
import sys

import requests

INDEX_URL = "https://bulletins.psu.edu/programs/"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "program_data")
OUT_PATH = os.path.join(OUT_DIR, "non_up_programs.json")

HEADERS = {
    "User-Agent": "GradGPS-CatalogScraper/1.0 (educational use; mkrokosz06@gmail.com)"
}

# Filter ids come from the index page's own checkbox labels; they're resolved from
# the page on every run rather than trusted as constants.
_LABELS = {"up": "University Park", "bacc": "Baccalaureate Degree", "assoc": "Associate Degree"}

_ITEM_RE = re.compile(r'<li id="isotope-item\d+" class="([^"]*)">(.*?)</li>', re.S)
_TITLE_RE = re.compile(r'<span class="title">(.*?)</span>', re.S)


def _filter_ids(page: str) -> dict[str, str]:
    ids = {}
    for key, label in _LABELS.items():
        m = re.search(r'id="(filter_\d+)"[^>]*/><label[^>]*>\s*' + re.escape(label) + r'\s*<', page)
        if not m:
            sys.exit(f"Could not find the '{label}' filter on {INDEX_URL} — page layout changed?")
        ids[key] = m.group(1)
    return ids


def parse_index(page: str) -> tuple[list[str], list[str]]:
    """Return (up_degree_programs, non_up_degree_programs), each sorted."""
    ids = _filter_ids(page)
    up, non_up = set(), set()
    for cls, body in _ITEM_RE.findall(page):
        classes = cls.split()
        if ids["bacc"] not in classes and ids["assoc"] not in classes:
            continue  # minors/certificates are scoped separately (credentials/)
        t = _TITLE_RE.search(body)
        if not t:
            continue
        name = html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip()
        (up if ids["up"] in classes else non_up).add(name)
    # A name the bulletin lists at UP under one entry is UP, whatever else it says.
    return sorted(up), sorted(non_up - up)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    resp = requests.get(INDEX_URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    up, non_up = parse_index(resp.text)
    print(f"Degree programs: {len(up)} at University Park, {len(non_up)} not offered there")
    # Sanity floor: a broken parse must never write a file that hides nothing (or
    # everything). The bulletin had 188 UP / 226 non-UP entries in Sept 2026.
    if len(up) < 150 or len(non_up) < 150:
        sys.exit("Counts implausibly low — refusing to write.")
    if args.dry_run:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"source": INDEX_URL, "non_up_programs": non_up}, f, indent=1)
        f.write("\n")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
