"""
scrape_gen_ed_courses.py
------------------------
Scrapes the PSU undergraduate bulletin for all courses that carry gen ed
attribute designations (GA, GN, GH, GS, GHW, US, IL, GWS, W).

Outputs:
  - gen_ed_courses.json    mapping course_code -> {title, credits, attrs, multi_category}
  - gen_ed_courses.csv     flat table for inspection

Then call load_gen_ed_courses() to write to DynamoDB, replacing the manual
pool entries in seed_gen_ed.py with comprehensive scraped data.

Usage:
  python scripts/scrape_gen_ed_courses.py             # scrape + save JSON/CSV
  python scripts/scrape_gen_ed_courses.py --load      # scrape + load into DynamoDB

Takes ~5-10 minutes for all ~274 departments.
"""

import re
import csv
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from bs4 import BeautifulSoup

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(str(Path(__file__).parent.parent))

BASE      = "https://bulletins.psu.edu"
INDEX_URL = f"{BASE}/university-course-descriptions/undergraduate/"

# All PSU gen ed attribute codes we care about
GEN_ED_CODES = {"GA", "GN", "GH", "GS", "GHW", "GQ", "US", "IL", "GWS"}

# The PSU bulletin marks each designation in its own element as
#   "General Education: Health and Wellness (GHW)"
# A course may carry several such lines (e.g. an interdomain GH + GHW course).
# We capture ONLY the parenthesised code that follows a "General Education:"
# label — this avoids scooping up stray two-letter tokens from the prose,
# which was the fatal flaw of the previous whole-text regex.
_DESIGNATION_RE = re.compile(
    r"General\s+Education:[^()\n]*?\(([A-Z]{2,3})\)",
    re.IGNORECASE,
)

# The Cultures requirements (US / IL) are labelled WITHOUT the
# "General Education:" prefix — e.g. "United States Cultures (US)",
# "International Cultures (IL)". Captured separately so we don't have to
# loosen the domain pattern (which would start matching "Bachelor of Arts:"
# degree-requirement lines).
_CULTURE_RE = re.compile(
    r"(?:United\s+States|International)\s+Cultures\s*\((US|IL)\)",
    re.IGNORECASE,
)

# Credit count pattern: "(3 credits)", "3 Credits", "(1-3)"
_CREDITS_RE = re.compile(r"\(?\b(\d+(?:\.\d+)?)\s*credits?\b\)?", re.IGNORECASE)

# Course code: "CHEM 110", "PHYS 211W", "ANTH 140N"
_CODE_RE = re.compile(r"\b([A-Z]{2,6})\s+(\d+[A-Z]?)\b")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "PSU-GradGPS-Scraper/1.0 (educational use)"


# ---------------------------------------------------------------------------
# Bulletin helpers
# ---------------------------------------------------------------------------

def get_soup(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=15)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            if attempt == retries - 1:
                print(f"  FAILED: {url} — {e}", flush=True)
                return None
            time.sleep(2 ** attempt)


def get_all_departments() -> list[tuple[str, str]]:
    soup = get_soup(INDEX_URL)
    if not soup:
        return []
    seen, depts = set(), []
    for a in soup.select("a[href*='/university-course-descriptions/undergraduate/']"):
        href = a["href"]
        parts = href.rstrip("/").split("/")
        if len(parts) >= 2 and parts[-2] == "undergraduate" and parts[-1]:
            url = href if href.startswith("http") else BASE + href
            if url not in seen:
                seen.add(url)
                depts.append((a.get_text(strip=True), url))
    return depts


# ---------------------------------------------------------------------------
# Attribute extraction
# ---------------------------------------------------------------------------

def _extract_attrs(text: str) -> set[str]:
    """Return the gen ed attribute codes the course is officially designated
    with — read only from 'General Education: … (CODE)' labels."""
    found = {m.group(1).upper() for m in _DESIGNATION_RE.finditer(text)}
    found |= {m.group(1).upper() for m in _CULTURE_RE.finditer(text)}
    return found & GEN_ED_CODES


def _extract_credits(text: str) -> float:
    m = _CREDITS_RE.search(text)
    if m:
        return float(m.group(1))
    return 3.0  # sensible default for PSU gen ed courses


def scrape_department(dept_url: str) -> list[dict]:
    """
    Scrape one department page and return courses with gen ed attributes.
    Returns list of dicts: {code, title, credits, attrs, multi_category}
    """
    soup = get_soup(dept_url)
    if not soup:
        return []

    results = []

    # PSU bulletin uses div.courseblock for each course
    blocks = soup.select(".courseblock")
    if not blocks:
        # Fallback: scan full page text
        return _fallback_scrape(soup)

    for block in blocks:
        block_text = block.get_text(" ", strip=True)
        attrs = _extract_attrs(block_text)
        if not attrs:
            continue  # no gen ed designation — skip

        # Extract course code from title line
        title_el = block.select_one(".courseblocktitle") or block.find(["strong", "b"])
        title_text = title_el.get_text(" ", strip=True) if title_el else block_text[:120]

        code_m = _CODE_RE.search(title_text)
        if not code_m:
            continue
        # Normalise trailing W/H/N attribute suffixes to match transcript codes
        # (e.g. "SOC 119N" → "SOC 119"), same rule as transcript_parser.
        course_code = re.sub(r"[WHN]$", "", f"{code_m.group(1)} {code_m.group(2)}")

        # Strip the course code + number from title to get just the name
        title = _CODE_RE.sub("", title_text, count=1).strip(" :-–")
        title = _CREDITS_RE.sub("", title).strip(" ():-–")
        # Clean up trailing attribute codes from title
        for code in GEN_ED_CODES:
            title = re.sub(rf"\b{code}\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s{2,}", " ", title).strip(" ():-–,;")
        if not title:
            title = course_code

        credits = _extract_credits(block_text)
        multi_category = len(attrs) > 1  # interdomain if satisfies 2+ categories

        results.append({
            "code":           course_code,
            "title":          title,
            "credits":        credits,
            "attrs":          sorted(attrs),
            "multi_category": multi_category,
        })

    return results


def _fallback_scrape(soup: BeautifulSoup) -> list[dict]:
    """Scan full page text when .courseblock divs are absent. Anchors on each
    'General Education: … (CODE)' designation and grabs the nearest preceding
    course code."""
    text = soup.get_text(" ", strip=True)
    results = []
    for m in _DESIGNATION_RE.finditer(text):
        code = m.group(1).upper()
        if code not in GEN_ED_CODES:
            continue
        preceding = text[max(0, m.start() - 120):m.start()]
        codes = _CODE_RE.findall(preceding)
        if not codes:
            continue
        course_code = f"{codes[-1][0]} {codes[-1][1]}"
        results.append({
            "code":           course_code,
            "title":          course_code,
            "credits":        3.0,
            "attrs":          [code],
            "multi_category": False,
        })
    return results


# ---------------------------------------------------------------------------
# Main scrape
# ---------------------------------------------------------------------------

def scrape_all() -> dict[str, dict]:
    """
    Scrape all PSU departments and return a deduplicated dict:
      course_code -> {title, credits, attrs, multi_category}
    If a course appears in multiple depts (cross-listed), attrs are merged.
    """
    print("Fetching department list...", flush=True)
    depts = get_all_departments()
    print(f"Found {len(depts)} departments.\n", flush=True)

    courses: dict[str, dict] = {}

    for i, (name, url) in enumerate(depts, 1):
        print(f"[{i:>3}/{len(depts)}] {name}...", end=" ", flush=True)
        found = scrape_department(url)
        print(f"{len(found)} gen-ed courses", flush=True)

        for c in found:
            code = c["code"]
            if code in courses:
                # Merge attrs (cross-listed course may appear under two depts)
                existing_attrs = set(courses[code]["attrs"]) | set(c["attrs"])
                courses[code]["attrs"] = sorted(existing_attrs)
                courses[code]["multi_category"] = len(existing_attrs) > 1
            else:
                courses[code] = c

        time.sleep(0.3)  # be polite

    print(f"\nTotal unique gen-ed courses found: {len(courses)}", flush=True)
    return courses


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def save_json(courses: dict[str, dict], path: Path):
    path.write_text(json.dumps(courses, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"JSON written: {path}")


def save_csv(courses: dict[str, dict], path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["course_code", "title", "credits", "attrs", "multi_category"])
        for code, c in sorted(courses.items()):
            w.writerow([code, c["title"], c["credits"],
                        ";".join(c["attrs"]), c["multi_category"]])
    print(f"CSV written: {path}")


# ---------------------------------------------------------------------------
# DynamoDB loader
# ---------------------------------------------------------------------------

# Group thresholds and priority — kept here, not scraped (these are PSU policy)
GROUP_META = {
    "GQ":  ("GQ: Quantification",                "choose_credits", 6),
    "GA":  ("GA: Arts",                          "choose_credits", 3),
    "GN":  ("GN: Natural Sciences",              "choose_credits", 6),
    "GH":  ("GH: Humanities",                    "choose_credits", 3),
    "GS":  ("GS: Social and Behavioral Sciences","choose_credits", 3),
    "GHW": ("GHW: Health and Physical Activity", "choose_credits", 3),
    "US":  ("US: United States Cultures",        "choose_credits", 3),
    "IL":  ("IL: International Cultures",        "choose_credits", 3),
    "GWS": ("GWS: Writing Across the Curriculum","choose_courses", 3),
}

# Groups that must always be present regardless of scrape results
# (required / choose_one groups that aren't just pools of eligible courses).
# These are kept exactly as they appear in seed_gen_ed.py.
FIXED_GROUPS = [
    "First-Year Seminar",
    "Communication: Writing",
    "Communication: Oral",
    "Quantification",
    "Communication: Effective Speech",
]


def load_gen_ed_courses(courses: dict[str, dict], dry_run: bool = False):
    """
    Write scraped gen-ed course rows to DynamoDB under program_name='__GEN_ED__'.
    Only writes the choose_credits / choose_courses pool rows — the fixed
    required/choose_one groups (Writing, FYS, etc.) are managed by seed_gen_ed.py.

    Each row gets a SK of the form:  "<group>#<code>#scraped"
    This avoids colliding with the manually-seeded rows (which use an integer index).
    """
    from db import requirements_table

    PROGRAM = "__GEN_ED__"
    count = 0

    with requirements_table.batch_writer() as batch:
        for code, c in courses.items():
            for attr in c["attrs"]:
                if attr not in GROUP_META:
                    continue
                group_name, gtype, threshold = GROUP_META[attr]
                multi_cat = c["multi_category"]

                group_course = f"{group_name}#{code}#scraped"

                item = {
                    "program_name":      PROGRAM,
                    "group_course":      group_course,
                    "requirement_group": group_name,
                    "group_type":        gtype,
                    "group_threshold":   threshold,
                    "course_code":       code,
                    "course_title":      c["title"],
                    "credits":           str(c["credits"]),
                    "min_grade":         "D",
                    "required":          False,
                }
                if multi_cat:
                    item["multi_category"] = True

                if dry_run:
                    print(f"  [DRY RUN] {group_name}: {code} ({';'.join(c['attrs'])})"
                          f"{'  [multi]' if multi_cat else ''}")
                else:
                    batch.put_item(Item=item)
                count += 1

    verb = "Would write" if dry_run else "Wrote"
    print(f"\n{verb} {count} gen-ed pool rows to DynamoDB (program_name='{PROGRAM}').")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape PSU gen-ed course attributes from bulletin")
    parser.add_argument("--load",    action="store_true", help="Load into DynamoDB after scraping")
    parser.add_argument("--dry-run", action="store_true", help="Print rows instead of writing to DynamoDB")
    parser.add_argument("--from-json", metavar="FILE",   help="Load from existing JSON instead of scraping")
    args = parser.parse_args()

    scripts_dir = Path(__file__).parent

    if args.from_json:
        print(f"Loading courses from {args.from_json}...")
        courses = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        courses = scrape_all()
        save_json(courses, scripts_dir / "gen_ed_courses.json")
        save_csv(courses,  scripts_dir / "gen_ed_courses.csv")

    if args.load or args.dry_run:
        load_gen_ed_courses(courses, dry_run=args.dry_run)
    else:
        print("\nRun with --load to write to DynamoDB, or --dry-run to preview.")
