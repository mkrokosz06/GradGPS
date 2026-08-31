"""
Repairs junk course titles across the requirements catalog.

The PSU catalog scraper wrote credit-range strings ("1-0", "3") into
course_title on some bulletin page layouts (~25% of rows; scraper root cause
tracked separately). Repair sources, in priority order:

  1. The catalog itself — most common non-junk title for the same course code
     anywhere in the table (gen-ed rows included as a source: they come from
     the authoritative bulletin scrape).
  2. scripts/bulletin_course_titles.json — canonical titles for every PSU
     undergrad course (scrape_course_titles.py; rescrape ~5-10 min).
  3. scripts/gen_ed_courses.json — exact-code titles from the gen-ed scrape.
  4. Suffix-tolerant fallback — strip trailing attribute/section letters
     (MATH 140H -> MATH 140) and use the base-code title only when every
     source agrees on a single title for that base.
  5. PSU policy numbers — university-wide reserved course numbers (X94
     Research Projects, X95 Internship, X96 Independent Studies, X97
     Special Topics, X99 Foreign Studies) that have no bulletin listing.

Rows with no usable source are left untouched and reported.

Usage:
    python scripts/fix_junk_titles.py [--dry-run]
"""

import sys, os, re, json
from collections import Counter, defaultdict

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db import requirements_table

_JUNK_RE = re.compile(r"[\d\s./-]*")
# Group-instruction text leaked into title fields ("6 Additional Credits of...",
# "3 Credits") — junk as a repair target AND excluded as a title source. Anchored
# to digit-then-Credits so real titles like "2D Art" are untouched.
_PLACEHOLDER_RE = re.compile(r"^\d+\s*(additional\s+)?credits\b", re.IGNORECASE)
_BASE_RE = re.compile(r"^([A-Z]+ \d+)[A-Z]*$")

# Bulletin footnotes / cross-listing fragments that the scraper wrote into the
# title field instead of the course name — e.g. CAS 100's
# "Note:  , , or  may not be counted as part of the minor.", the leading-comma
# fragments left when a course code is stripped (", 100B , or 100C ‡"), and the
# footnote dagger markers (†/‡, plus the U+FFFD replacement char) the scraper
# left as titles. High-precision so it never flags a real title (verified
# against the full catalog — 0 legitimate titles caught).
_FOOTNOTE_RES = (
    re.compile(r"[†‡�]"),  # footnote markers/garbage: "(GWS) ‡†", "†"
    re.compile(r"^\s*,"),            # leading-comma fragment: ", 100B , or 100C ‡"
    re.compile(r"(?i)^\s*note\s*:"), # explicit footnote: "Note:  , , or  may not…"
    re.compile(r",\s*,"),            # empty enumeration gap where codes were stripped
    re.compile(r"(?i)^\s*students\s+may\b"),  # leaked minor policy: "Students may count up to…"
)


def _is_footnote(title: str) -> bool:
    return any(rx.search(title) for rx in _FOOTNOTE_RES)

# PSU-wide reserved course numbers (bulletin has no per-department listing)
_POLICY_NUMBERS = {
    "94": "Research Project",
    "95": "Internship",
    "96": "Independent Studies",
    "97": "Special Topics",
    "99": "Foreign Studies",
}
_POLICY_RE = re.compile(r"^[A-Z]+ \d(?:\d)?(\d{2})[A-Z]*$")


def _is_junk(title) -> bool:
    if not title:
        return True
    t = str(title).strip()
    return (_JUNK_RE.fullmatch(t) is not None
            or _PLACEHOLDER_RE.match(t) is not None
            or _is_footnote(t))


def _base(code: str) -> str | None:
    m = _BASE_RE.match(code)
    return m.group(1) if m else None


def fix_junk_titles(dry_run: bool = False) -> None:
    print("\nRepairing junk course titles across the catalog...")

    rows = []
    kwargs = {"ProjectionExpression": "program_name, group_course, course_code, course_title"}
    resp = requirements_table.scan(**kwargs)
    rows += resp["Items"]
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.scan(**kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        rows += resp["Items"]

    # ── Build title sources ──────────────────────────────────────────────────
    exact = defaultdict(Counter)     # code -> good titles seen in catalog
    for r in rows:
        code, title = r.get("course_code"), r.get("course_title")
        if code and not _is_junk(title):
            exact[code][str(title).strip()] += 1

    here = os.path.dirname(__file__)

    bulletin_path = os.path.join(here, "bulletin_course_titles.json")
    bulletin = {}
    if os.path.exists(bulletin_path):
        with open(bulletin_path, encoding="utf-8") as f:
            bulletin = {c: t for c, t in json.load(f).items() if not _is_junk(t)}

    gen_ed_path = os.path.join(here, "gen_ed_courses.json")
    gen_ed = {}
    if os.path.exists(gen_ed_path):
        with open(gen_ed_path, encoding="utf-8") as f:
            gen_ed = {c: v["title"] for c, v in json.load(f).items()
                      if v.get("title") and not _is_junk(v["title"])}

    base_titles = defaultdict(set)   # base code -> distinct titles across sources
    for code, counts in exact.items():
        if (b := _base(code)):
            base_titles[b].add(counts.most_common(1)[0][0])
    for source in (bulletin, gen_ed):
        for code, title in source.items():
            if (b := _base(code)):
                base_titles[b].add(title)

    def resolve(code: str) -> tuple[str, str] | None:
        if code in exact:
            return exact[code].most_common(1)[0][0], "catalog"
        if code in bulletin:
            return bulletin[code], "bulletin"
        if code in gen_ed:
            return gen_ed[code], "gen_ed_json"
        b = _base(code)
        if b and len(base_titles.get(b, ())) == 1:
            return next(iter(base_titles[b])), "base_code"
        pm = _POLICY_RE.match(code)
        if pm and pm.group(1) in _POLICY_NUMBERS:
            return _POLICY_NUMBERS[pm.group(1)], "policy_number"
        return None

    # ── Repair ───────────────────────────────────────────────────────────────
    fixed = Counter()
    unfixable_codes = set()
    for r in rows:
        if r["program_name"].startswith("__"):
            continue  # sentinel rows are sources, never targets
        code, title = r.get("course_code"), r.get("course_title")
        if not code or not _is_junk(title):
            continue
        hit = resolve(code)
        if hit is None:
            unfixable_codes.add(code)
            continue
        new_title, source = hit
        if not dry_run:
            requirements_table.update_item(
                Key={"program_name": r["program_name"], "group_course": r["group_course"]},
                UpdateExpression="SET course_title = :t",
                ExpressionAttributeValues={":t": new_title},
            )
        fixed[source] += 1

    total = sum(fixed.values())
    verb = "Would repair" if dry_run else "Repaired"
    print(f"  {verb} {total} rows "
          f"(catalog: {fixed['catalog']}, bulletin: {fixed['bulletin']}, "
          f"gen-ed json: {fixed['gen_ed_json']}, base-code: {fixed['base_code']}, "
          f"policy-number: {fixed['policy_number']}).")
    if unfixable_codes:
        print(f"  {len(unfixable_codes)} codes still lack any title source: "
              f"{sorted(unfixable_codes)[:10]}...")


if __name__ == "__main__":
    fix_junk_titles(dry_run="--dry-run" in sys.argv)
