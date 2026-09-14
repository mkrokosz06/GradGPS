"""
scrape_bulletin_courses.py
--------------------------
Scrapes the canonical title AND credit value for every undergraduate course
from the PSU bulletin course-description pages.

Why this exists
---------------
The requirements table stores one row per (program, requirement slot, course),
so a widely-required course has hundreds of rows — MATH 140 has 478 across 138
programs, because a bulletin page repeats a shared requirement once per subplan.
Those rows were scraped at different times from inconsistently formatted pages
and they disagree: of MATH 140's 478, 355 say 4 credits, 37 say 3, 14 say 1, and
70 carry no credits at all. In production STAT 200 splits 217 rows saying 3
against 139 saying 4 — and the bulletin says 4, so even a majority vote is wrong.

The bulletin publishes one authoritative number per course, so read that instead
of arguing with the catalog.

It also fixes titles. The old `scrape_course_titles.py` took `.courseblocktitle`
as one blob of text and stripped the credits back out with a regex, which is how
KINES 1 ended up stored as "Introduction to Outdoor Pursuits 1.5-/Maxi". The
bulletin actually puts them in separate elements:

    <div class="course_codetitle">KINES 1: Introduction to Outdoor Pursuits</div>
    <div class="course_credits">1.5-3 Credits/Maximum of 12</div>

so read each field directly and nothing needs unpicking.

Credit formats — 4 shapes cover 2600 sampled strings:
    "4 Credits"                        -> 4
    "1.5-3 Credits"                    -> 1.5, max 3
    "1.5 Credits/Maximum of 99"        -> 1.5          ("Maximum of" is a repeat
    "1.5-3 Credits/Maximum of 12"      -> 1.5, max 3    cap across enrollments,
                                                        not this term's credits)

Output (both written, so `fix_junk_titles.py` keeps working):
    scripts/bulletin_courses.json       code -> {title, credits, credits_max}
    scripts/bulletin_course_titles.json code -> title

Usage:
    python scripts/scrape_bulletin_courses.py            # ~5-10 min, ~274 depts
    python scripts/scrape_bulletin_courses.py --limit 5  # smoke test
"""

import re
import sys
import json
import time
import argparse
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(str(Path(__file__).parent))
from scrape_gen_ed_courses import get_soup, get_all_departments, _CODE_RE

OUT_COURSES = Path(__file__).parent / "bulletin_courses.json"
OUT_TITLES  = Path(__file__).parent / "bulletin_course_titles.json"

# "4 Credits" / "1.5-3 Credits" — anchored at the start so the trailing
# "/Maximum of 12" (a repeat cap, not this term's credits) is ignored.
_CREDITS_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*credits?\b",
    re.IGNORECASE,
)


def parse_credits(text: str) -> tuple[float, float | None] | None:
    """'1.5-3 Credits/Maximum of 12' -> (1.5, 3).  '4 Credits' -> (4.0, None)."""
    if not text:
        return None
    m = _CREDITS_RE.match(text.strip())
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else None
    if hi is not None and hi <= lo:      # malformed range — treat as fixed
        hi = None
    return lo, hi


def parse_code_title(text: str) -> tuple[str, str] | None:
    """'KINES 1: Introduction to Outdoor Pursuits' -> ('KINES 1', 'Introduction…')."""
    if not text:
        return None
    m = _CODE_RE.search(text)
    if not m:
        return None
    code = f"{m.group(1)} {m.group(2)}"
    title = text[m.end():].strip(" :–—- ")
    title = re.sub(r"\s{2,}", " ", title).strip()
    return code, title


def scrape_department(dept_url: str) -> dict[str, dict]:
    soup = get_soup(dept_url)
    if not soup:
        return {}
    out: dict[str, dict] = {}
    for block in soup.select(".courseblocktitle"):
        ct = block.select_one(".course_codetitle")
        if not ct:
            continue
        parsed = parse_code_title(ct.get_text(" ", strip=True))
        if not parsed:
            continue
        code, title = parsed
        if not title:
            continue

        credits = credits_max = None
        cr_el = block.select_one(".course_credits")
        if cr_el:
            got = parse_credits(cr_el.get_text(" ", strip=True))
            if got:
                credits, credits_max = got

        rec = {"title": title}
        if credits is not None:
            rec["credits"] = credits
            if credits_max is not None:
                rec["credits_max"] = credits_max
        out[code] = rec
    return out


def scrape_all(limit: int | None = None) -> dict[str, dict]:
    print("Fetching department list...", flush=True)
    depts = get_all_departments()
    if limit:
        depts = depts[:limit]
    print(f"Found {len(depts)} departments.", flush=True)

    courses: dict[str, dict] = {}
    for i, (name, url) in enumerate(depts, 1):
        for code, rec in scrape_department(url).items():
            courses.setdefault(code, rec)
        if i % 25 == 0 or i == len(depts):
            have_cr = sum(1 for r in courses.values() if "credits" in r)
            print(f"  [{i}/{len(depts)}] {len(courses)} courses, {have_cr} with credits",
                  flush=True)
        time.sleep(0.3)      # be polite to bulletins.psu.edu
    return courses


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only scrape the first N departments")
    ap.add_argument("--dry-run", action="store_true", help="don't write the files")
    args = ap.parse_args()

    courses = scrape_all(args.limit)
    if not courses:
        print("\nNothing scraped — refusing to overwrite the existing files.")
        sys.exit(1)

    with_credits = sum(1 for r in courses.values() if "credits" in r)
    ranges = sum(1 for r in courses.values() if "credits_max" in r)
    print(f"\n{len(courses)} courses  |  {with_credits} with credits "
          f"({with_credits / len(courses) * 100:.1f}%)  |  {ranges} variable-credit")

    if args.dry_run:
        print("(dry run — nothing written)")
        sys.exit(0)

    OUT_COURSES.write_text(
        json.dumps(courses, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    titles = {c: r["title"] for c, r in courses.items()}
    OUT_TITLES.write_text(
        json.dumps(titles, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"Wrote {OUT_COURSES}\nWrote {OUT_TITLES} ({len(titles)} titles)")
