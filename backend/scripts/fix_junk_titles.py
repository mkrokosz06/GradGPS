"""
Repairs junk course titles across the requirements catalog.

The PSU catalog scraper wrote credit-range strings ("1-0", "3") into
course_title on some bulletin page layouts (~25% of rows; scraper root cause
tracked separately). Repair sources, in priority order:

  1. The catalog itself — most common non-junk title for the same course code
     anywhere in the table (gen-ed rows included as a source: they come from
     the authoritative bulletin scrape).
  2. scripts/gen_ed_courses.json — exact-code titles from the same scrape.
  3. Suffix-tolerant fallback — strip trailing attribute/section letters
     (MATH 140H -> MATH 140) and use the base-code title only when every
     source agrees on a single title for that base.

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


def _is_junk(title) -> bool:
    if not title:
        return True
    t = str(title).strip()
    return _JUNK_RE.fullmatch(t) is not None or _PLACEHOLDER_RE.match(t) is not None


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

    gen_ed_path = os.path.join(os.path.dirname(__file__), "gen_ed_courses.json")
    gen_ed = {}
    if os.path.exists(gen_ed_path):
        with open(gen_ed_path, encoding="utf-8") as f:
            gen_ed = {c: v["title"] for c, v in json.load(f).items()
                      if v.get("title") and not _is_junk(v["title"])}

    base_titles = defaultdict(set)   # base code -> distinct titles across sources
    for code, counts in exact.items():
        if (b := _base(code)):
            base_titles[b].add(counts.most_common(1)[0][0])
    for code, title in gen_ed.items():
        if (b := _base(code)):
            base_titles[b].add(title)

    def resolve(code: str) -> tuple[str, str] | None:
        if code in exact:
            return exact[code].most_common(1)[0][0], "catalog"
        if code in gen_ed:
            return gen_ed[code], "gen_ed_json"
        b = _base(code)
        if b and len(base_titles.get(b, ())) == 1:
            return next(iter(base_titles[b])), "base_code"
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
          f"(catalog: {fixed['catalog']}, gen-ed json: {fixed['gen_ed_json']}, "
          f"base-code: {fixed['base_code']}).")
    if unfixable_codes:
        print(f"  {len(unfixable_codes)} codes still lack any title source "
              f"(need bulletin course-description scrape).")


if __name__ == "__main__":
    fix_junk_titles(dry_run="--dry-run" in sys.argv)
