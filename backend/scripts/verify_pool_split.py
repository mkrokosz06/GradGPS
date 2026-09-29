"""
Independent verification of the requirement-pool split.

The scraper is not allowed to be its own witness. This script re-fetches every
University Park degree program's bulletin page and re-derives its pools with a
SECOND, deliberately simple parser written from the page structure rather than
from `scrape_psu.py`'s code — then compares the two. A program where the two
disagree is printed for a human to read, because a silent disagreement is
exactly the failure mode that put CYBER 100 out of a student's plan.

It also diffs the new scrape against a baseline scrape and refuses to be quiet
about the dangerous direction: a program must never come out of this change
requiring FEWER courses than it did before.

    cd backend
    python scripts/verify_pool_split.py \
        --new  ../PSU_Major_Requirements.xlsx \
        --base /path/to/baseline_PSU_Major_Requirements.xlsx

    --limit N      check only the first N changed programs
    --offline      skip the re-fetch; run the baseline diff only
    --report FILE  write the full findings (default: stdout only)
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import requests
from bs4 import BeautifulSoup

from routers.programs import is_degree_program, is_up_program

HEADERS = {
    "User-Agent": "GradGPS-CatalogScraper/1.0 (educational use; mkrokosz06@gmail.com)"
}

POOL_TYPES = ("choose_credits", "choose_courses")

# "Select 3 credits", "Select 3-4 credits", "Choose 6 or more credits", and a
# qualifier before the number: "Select a minimum of 12 credits", "Select at
# least 6 credits". Phrased here independently of scrape_psu._POOL_HEADER: the
# number may be preceded by up to four words, none of them a cap ("maximum",
# "up to") — a cap limits part of a pool rather than opening one.
_POOL_RE = re.compile(
    r"\b(?:select|choose|minimum)\b(?:\s+(?!maximum\b|up\b)[a-z]+){0,4}?\s+(\d+)"
    r"(?:\s*[-–—]\s*\d+)?(?:\s+[a-z-]+){0,2}?\s+credits?\b",
    re.I,
)
# "Pick one block" worded without "of the following": "Select one
# concentration", "Select an emphasis", "Select one sequence of the following",
# "...with selected emphasis area". Written separately from scrape_psu._PICK_BLOCK.
_BLOCK_RE = re.compile(
    r"\b(?:select|choose|take|complete)\s+(?:one|an?)\s+(?:approved\s+)?"
    r"(?:sequence|concentration|emphasis(?:\s+area)?|track|pathway)s?\b(?!\s+of\s+\d)"
    r"|\bwith\s+(?:a\s+)?selected\s+emphasis\s+area\b"
    r"|\b(?:select|choose)\s+(?:course\s+)?set\s+[a-z]\s+or\s+[a-z]\b",
    re.I,
)
_POOL_COUNT_RE = re.compile(
    r"(?:select|choose|complete|take)\s+"
    r"(?:one|two|three|four|five|six|\d+)\s+of\s+the\s+following",
    re.I,
)
_CODE_RE = re.compile(
    r"\b([A-Z]{2,6}(?:-[A-Z]{1,6})?|[A-Z](?:-[A-Z]){1,3})\s{0,2}(\d{1,3}[A-Z]?)\b"
)

# Short codes (1-2 digits) are only real if the bulletin lists them. Without this
# gate the regex invents requirements out of prose and footnotes — "II 1",
# "MATLAB 3" and "SCM 0" all showed up as courses the scraper had supposedly lost.
_BULLETIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "bulletin_courses.json")
try:
    with open(_BULLETIN_PATH, encoding="utf-8") as _f:
        _BULLETIN = json.load(_f)
except Exception:
    _BULLETIN = {}


def _code_ok(dept: str, num: str) -> bool:
    digits = "".join(ch for ch in num if ch.isdigit())
    if len(digits) >= 3:
        return True
    return f"{dept} {num}" in _BULLETIN


# ── Second parser ────────────────────────────────────────────────────────────
#
# Written against the page, not against scrape_psu.py: walk the courselist
# tables top to bottom; a comment row matching _POOL_RE opens a pool; rows whose
# code cell is wrapped in <div class="blockindent"> belong to it; the first
# unindented course row closes it.

def _focus_codes(soup) -> list[frozenset]:
    """Every course in the plan tab's plain courselists — the Application Focus
    menus (Data Sciences, HCDD) — read from cell text. The scraper reads the same
    lists from their links; the two must agree."""
    tab = soup.find(id="suggestedacademicplantextcontainer")
    if tab is None:
        return []
    out = []
    for table in tab.find_all("table", class_="sc_courselist"):
        for tr in table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if not tds or tr.find("span", class_="courselistcomment") is not None:
                continue
            for part in tds[0].get_text(" ", strip=True).split("&"):
                codes = frozenset(f"{m.group(1)} {m.group(2)}" for m in _CODE_RE.finditer(part)
                                  if _code_ok(m.group(1), m.group(2)))
                if codes and codes not in out:
                    out.append(codes)
    # ETI, Cybersecurity and IT Ethics publish their areas as bulleted lists. A
    # course entry is a leaf <li> that is almost all course codes; an area's notes
    # (which cite prerequisites) are sentences. Checked here by the share of the
    # entry's words that are course codes, independently of the scraper's rule.
    for li in tab.find_all("li"):
        if li.find("li"):
            continue
        text = li.get_text(" ", strip=True).replace("\xa0", " ")
        found = [(m.group(1), m.group(2)) for m in _CODE_RE.finditer(text) if _code_ok(m.group(1), m.group(2))]
        words = re.findall(r"[A-Za-z]+", text)
        if not found or len(found) * 2 < len(words) - len(found) - text.lower().count(" or "):
            continue
        for d, n in found:
            code = frozenset({f"{d} {n}"})
            if code not in out:
                out.append(code)
    # A course and its writing / honors twin (MKTG 301, MKTG 301W) are one
    # requirement: the audit strips the suffix, so either spelling satisfies it.
    merged: dict[str, set] = {}
    for group in out:
        for code in group:
            base = re.sub(r"(\d)[WHMXY]$", r"\1", code)
            merged.setdefault(base, set()).add(code)
    return [frozenset(v) for v in merged.values()]


def pools_from_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("div", {"id": re.compile(r"requirementstab", re.I)}) or soup
    pools: list[dict] = []
    focus = _focus_codes(soup)
    block = None                # the open "pick one block" pool, if any
    emph = None                 # ...only if it was an "emphasis/concentration" block
    for table in root.find_all("table", class_=re.compile(r"sc_courselist")):
        current = None          # a new table is a new context
        # An emphasis table under an <h6> continues the block pool opened by
        # "Select an emphasis" in the table before it; every course is a member.
        prev = table.find_previous(["h2", "h3", "h4", "h5", "h6", "table"])
        continuing = emph is not None and prev is not None and prev.name == "h6"
        if continuing:
            current = emph
        else:
            block = emph = None
        for tr in table.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if not tds:
                continue
            # "Prescribed Courses" / "Supporting Courses and Related Areas" start
            # a new sub-section and end whatever list came before.
            if any("areaheader" in c for c in (tr.get("class") or [])):
                if not continuing:
                    current = None
                    block = emph = None
                continue
            text = " ".join(td.get_text(" ", strip=True) for td in tds)
            # A code cell holds one requirement, but it can spell it several ways:
            #   "BIOL 114 & BIOL 115"      -> two courses, both required
            #   "EE 471/AERSP 490/NUCE 490" -> ONE course, cross-listed three ways
            # Splitting on "&" gives the separate courses; within each part the
            # codes are aliases of one another, so they become an alternative
            # group and the scraper is right to store only one of them.
            cell = tds[0].get_text(" ", strip=True)
            codes = [
                frozenset(f"{m.group(1)} {m.group(2)}"
                          for m in _CODE_RE.finditer(part)
                          if _code_ok(m.group(1), m.group(2)))
                for part in cell.split("&")
            ]
            codes = [c for c in codes if c]
            # An instruction row (<span class="courselistcomment">) is never a
            # course, even when its prose names one: Psychology heads a pool
            # "Select 15 credits ... can be replaced by LA 495".
            if tr.find("span", class_="courselistcomment") is not None:
                codes = []
            indented = any(td.find("div", class_="blockindent") for td in tds)

            if continuing:
                if codes:
                    current["codes"].extend(codes)
                continue

            if not codes:
                # Inside a pick-one block, an indented header ("Select 12 credits
                # from the following:" under "2. Geographic Information
                # Systems") belongs to one block and opens nothing new.
                if block is not None and current is block and indented:
                    continue
                # A pool header either states credits ("Select 3-4 credits from
                # the following:") or counts options ("Select one of the
                # following sequences:"). Both open a list.
                m = _POOL_RE.search(text) or _POOL_COUNT_RE.search(text)
                # The focus requirement, however worded: "Select 12 credits from
                # … Application Focus", "must complete 12 credits from a single
                # Application Focus" (ETI), "Focus Area: Select 12 credits" (IT Ethics).
                low = text.lower()
                is_focus = ("application focus" in low or low.startswith("focus area")) and \
                    re.search(r"\b\d+\s+credits\b", low)
                if is_focus and focus:
                    # The pool's members are the plan tab's focus menus.
                    pools.append({"codes": list(focus), "confirmed": True})
                    current = None
                    continue
                if m or _BLOCK_RE.search(text):
                    current = {"codes": []}
                    pools.append(current)
                    block = current if (_POOL_COUNT_RE.search(text) or _BLOCK_RE.search(text)) else None
                    emph = current if _BLOCK_RE.search(text) else None
                # A comment row that is not a pool header does NOT end the list.
                # Pages use them as sub-headings inside a long option list
                # ("European Art:"), and closing on them split pools the page
                # keeps whole. The areaheader reset above is what separates
                # Kinesiology's emphasis blocks from the pool before them.
                continue

            if current is None:
                continue
            if indented:
                current["confirmed"] = True
            else:
                # Unindented: either this comment row never introduced a list at
                # all (a standalone "Select 1 credit of First-Year Seminar"), or
                # the list has ended. Either way the row is not a pool member.
                current = None
                continue
            current["codes"].extend(codes)
    return [p for p in pools if p["codes"]]


# ── Scraper output ───────────────────────────────────────────────────────────

def pools_from_frame(df: pd.DataFrame) -> list[dict]:
    """Pools as the scraper recorded them, for one program. A per-area
    Application Focus pool is a view of the any-area pool ("*"), which is the one
    checked against the page."""
    rows = df[df.group_type.isin(POOL_TYPES)]
    if "focus_area" in rows:
        rows = rows[rows.focus_area.isna() | rows.focus_area.isin(["", "*"])]
    out = []
    for (_group, thr, seq), grp in rows.groupby(
        ["requirement_group", "group_threshold", "pool_seq"], dropna=False
    ):
        out.append({
            "seq": None if pd.isna(seq) else int(seq),
            "codes": set(grp.course_code),
        })
    return out


def up_degree_programs(df: pd.DataFrame) -> list[str]:
    degrees = df.groupby("program_name")["degree"].apply(
        lambda s: {str(d) for d in s if str(d) not in ("nan", "", "N/A")}
    )
    return [
        name for name in sorted(df.program_name.unique())
        if is_up_program(name) and is_degree_program(name, degrees.get(name, set()))
    ]


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


# ── Comparisons ──────────────────────────────────────────────────────────────

def compare_to_page(scraped: list[dict], page: list[dict]) -> list[str]:
    """Findings, empty when the two parsers agree."""
    problems = []
    s_sets = [frozenset(p["codes"]) for p in scraped]
    # Each page pool is a list of alternative-groups; it is satisfied by a
    # scraper pool holding any one code from each group.
    p_groups = [list(p["codes"]) for p in page]
    p_sets = [frozenset().union(*g) if g else frozenset() for g in p_groups]

    if len(s_sets) != len(p_sets):
        problems.append(f"pool COUNT differs: scraper {len(s_sets)}, page {len(p_sets)}")

    # A requirement the page lists that the scraper represents by NO code at all
    # is the serious direction — the student is never offered it.
    scr_codes = set().union(*s_sets) if s_sets else set()
    unrepresented = [sorted(g) for groups in p_groups for g in groups
                     if not (g & scr_codes)]
    if unrepresented:
        problems.append(f"requirements MISSING from scrape: {unrepresented}")
    page_codes = set().union(*p_sets) if p_sets else set()
    if scr_codes - page_codes:
        problems.append(f"pool courses the page does not list: {sorted(scr_codes - page_codes)}")

    # Match pools by MEMBERSHIP, not by position. Sorting both lists and zipping
    # them made one extra or missing pool report every later pool as a mismatch,
    # which buried the real disagreements under an avalanche of shifted pairs.
    def covers(scr: frozenset, groups: list) -> bool:
        """Does this scraper pool represent exactly this page pool — one code
        from each alternative-group, and nothing extra?"""
        if any(not (g & scr) for g in groups):
            return False
        return not (scr - frozenset().union(*groups)) if groups else not scr

    unmatched_p = []
    remaining = list(s_sets)
    for groups in p_groups:
        hit = next((scr for scr in remaining if covers(scr, groups)), None)
        if hit is None:
            unmatched_p.append(sorted(frozenset().union(*groups)) if groups else [])
        else:
            remaining.remove(hit)
    for a in remaining:
        problems.append(f"pool only in scraper: {sorted(a)}")
    for b in unmatched_p:
        problems.append(f"pool only on page: {b}")
    return problems


def compare_to_baseline(base: pd.DataFrame, new: pd.DataFrame) -> dict:
    base_codes = set(base.course_code)
    new_codes = set(new.course_code)
    base_pools = pools_from_frame(base)
    new_pools = pools_from_frame(new)
    return {
        "lost_courses": sorted(base_codes - new_codes),
        "gained_courses": sorted(new_codes - base_codes),
        "base_pool_count": len(base_pools),
        "new_pool_count": len(new_pools),
        "base_rows": len(base),
        "new_rows": len(new),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--report", default="")
    args = ap.parse_args(argv)

    new_df = pd.read_excel(args.new, sheet_name="All Requirements")
    base_df = pd.read_excel(args.base, sheet_name="All Requirements")
    if "pool_seq" not in base_df.columns:
        base_df["pool_seq"] = None

    programs = up_degree_programs(new_df)
    print(f"{len(programs)} University Park degree programs in the new scrape\n")

    changed, findings = [], defaultdict(list)
    lost_anywhere = []

    for name in programs:
        n = new_df[new_df.program_name == name]
        b = base_df[base_df.program_name == name]
        if b.empty:
            findings[name].append("not present in the baseline scrape")
            changed.append(name)
            continue
        diff = compare_to_baseline(b, n)
        if diff["lost_courses"]:
            lost_anywhere.append((name, diff["lost_courses"]))
        if (diff["new_pool_count"] != diff["base_pool_count"]
                or diff["lost_courses"] or diff["gained_courses"]):
            changed.append(name)
            findings[name].append(
                f"pools {diff['base_pool_count']} -> {diff['new_pool_count']}, "
                f"rows {diff['base_rows']} -> {diff['new_rows']}"
            )
            if diff["lost_courses"]:
                findings[name].append(f"LOST courses: {diff['lost_courses']}")
            if diff["gained_courses"]:
                findings[name].append(f"gained courses: {diff['gained_courses']}")

    print(f"{len(changed)} programs changed\n")

    disagreements = []
    if not args.offline:
        targets = changed[: args.limit] if args.limit else changed
        print(f"Re-checking {len(targets)} changed programs against the live bulletin...")
        for i, name in enumerate(targets, 1):
            urls = new_df[new_df.program_name == name].url.dropna().unique()
            if len(urls) == 0:
                findings[name].append("no url recorded — cannot verify")
                continue
            html = fetch(urls[0])
            print(f"  [{i:>3}/{len(targets)}] {name[:60]}", end="")
            if not html:
                findings[name].append("page fetch failed — NOT verified")
                print("  FETCH FAILED")
                continue
            problems = compare_to_page(
                pools_from_frame(new_df[new_df.program_name == name]),
                pools_from_page(html),
            )
            if problems:
                disagreements.append(name)
                findings[name].extend(problems)
                print("  DISAGREES")
            else:
                print("  ok")

    print("\n" + "=" * 72)
    print(f"  Programs checked            : {len(programs)}")
    print(f"  Programs changed            : {len(changed)}")
    print(f"  Disagree with the live page : {len(disagreements)}")
    print(f"  Programs that LOST a course : {len(lost_anywhere)}")
    print("=" * 72)
    if lost_anywhere:
        print("\nA lost course is the dangerous direction — a requirement the student")
        print("will no longer be told about. Every one of these needs reading:\n")
        for name, lost in lost_anywhere[:40]:
            print(f"  {name[:60]:<62} {lost}")
    if disagreements:
        print("\nPrograms where the two parsers disagree:\n")
        for name in disagreements[:40]:
            print(f"  {name}")
            for f in findings[name]:
                print(f"      {f}")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "programs": len(programs),
                    "changed": changed,
                    "disagreements": disagreements,
                    "lost": {n: c for n, c in lost_anywhere},
                    "findings": {k: v for k, v in findings.items()},
                },
                fh, indent=1,
            )
        print(f"\nFull report: {args.report}")

    return 1 if (disagreements or lost_anywhere) else 0


if __name__ == "__main__":
    sys.exit(main())
