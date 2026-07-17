"""
Scrape a Penn State bulletin "Suggested Academic Plan" into a plan-template JSON
(the Phase 3a schema in ../sap_templates/).

PSU bulletins run on CourseLeaf; the SAP is a structured `table.sc_plangrid`, so
this is a deterministic HTML parse — NOT an LLM extraction (which mis-placed
credits in early testing).  Each `<td>` carries a `header` attribute encoding its
exact year/term, so course-to-semester placement is exact.

Usage:
    python scripts/scrape_sap.py                 # scrape the PROGRAMS list, validate, write
    python scripts/scrape_sap.py --dry-run       # parse + validate only, write nothing
    python scripts/scrape_sap.py --check-catalog # also cross-check codes vs the catalog

Only templates that pass validation are written — a bad scrape never goes live.
"""

import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from plan_templates import validate_template, fixed_codes, pinned_course_codes

_OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sap_templates")
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".sap_cache")

# Catalog program_name  →  bulletin SAP URL.  program_name MUST match the
# requirements table exactly so the app can find the template (see is_up_program).
PROGRAMS: list[dict] = [
    {"program_name": "Accounting, B.S. (Business)", "degree": "B.S.",
     "url": "https://bulletins.psu.edu/undergraduate/colleges/smeal-business/accounting-bs/"},
    {"program_name": "Marketing, B.S. (Business)", "degree": "B.S.",
     "url": "https://bulletins.psu.edu/undergraduate/colleges/smeal-business/marketing-bs/"},
    {"program_name": "Psychology, B.S. (Liberal Arts)", "degree": "B.S.",
     "url": "https://bulletins.psu.edu/undergraduate/colleges/liberal-arts/psychology-bs/"},
]

# Gen-ed category tokens the bulletin uses in parentheses, normalized to the
# catalog's category codes.  "(N)" is the bulletin's shorthand for GN.
_GENED_TOKENS = {"GQ", "GS", "GH", "GA", "GN", "GHW", "GWS", "US", "IL", "N"}
_GENED_NORMALIZE = {"N": "GN"}

# A course code: 2-5 letters, space, 1-3 digits, optional single attribute letter.
_CODE_RE = re.compile(r"\b([A-Z]{2,5})\s+(\d{1,3}[A-Z]?)\b")


def fetch(url: str) -> str:
    """Fetch a bulletin page (cached to scripts/.sap_cache to avoid re-hitting the
    server during development)."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    key = re.sub(r"[^a-z0-9]+", "_", url.lower()).strip("_") + ".html"
    path = os.path.join(_CACHE_DIR, key)
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (GradGPS SAP scraper)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "replace")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return html


def _cell_text(td) -> str:
    """Readable text of a cell with footnote superscripts removed, nbsp fixed, and
    en/em/undecoded dashes normalized to a plain hyphen."""
    for sup in td.find_all("sup"):
        sup.extract()
    txt = td.get_text(" ", strip=True).replace("\xa0", " ")
    txt = txt.replace("�", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", txt).strip()


def _cell_codes(td, text: str) -> list[str]:
    """Course codes in a cell.  Merges two sources so mixed cells are complete:
    each link's onclick=showCourse(this,'CODE') (authoritative, includes shorthand
    like a bare '30H' that renders as ENGL 30H) PLUS a regex over the text (catches
    unlinked plain-text codes like a leading 'CAS 100,')."""
    onclick: list[str] = []
    for a in td.find_all("a"):
        m = re.search(r"showCourse\(this,\s*'([^']+)'\)", a.get("onclick", ""))
        if m:
            onclick.append(re.sub(r"\s+", " ", m.group(1)).strip())
    regexed = [f"{m.group(1)} {m.group(2)}" for m in _CODE_RE.finditer(text)]
    # de-dupe (case-insensitive), preserve order, links first
    seen, out = set(), []
    for c in onclick + regexed:
        if c.upper() not in seen:
            seen.add(c.upper()); out.append(c)
    return out


def _detect_gened(text: str) -> str | None:
    for m in re.finditer(r"\(([A-Z]{1,3})\)", text):
        tok = m.group(1)
        if tok in _GENED_TOKENS:
            return _GENED_NORMALIZE.get(tok, tok)
    return None


def _classify(text: str, codes: list[str], credits: float) -> dict:
    """Map a plan-grid cell into a typed template slot."""
    low = text.lower()
    gened = _detect_gened(text)

    if "world language" in low:
        return {"type": "pool", "ref": "world_language", "label": text, "credits": credits}
    if "business breadth" in low:
        return {"type": "pool", "ref": "business_breadth", "label": "Business Breadth Course", "credits": credits}
    # A departmental elective pool: a "NXX" course-number wildcard (ACCTG 4XX,
    # MKTG 4XX) or a "<Dept> Elective" label, optionally anchored by a real course.
    if re.search(r"\b\d?XX\b", text) or ("elective" in low and codes):
        slot = {"type": "pool", "ref": "major_elective", "label": text, "credits": credits}
        if codes:
            slot["codes"] = codes
        return slot
    if low in ("elective", "electives") or (low.startswith("elective") and not codes):
        return {"type": "elective", "label": "Elective", "credits": credits}
    if "general education" in low or (gened and not codes):
        return {"type": "gen_ed", "category": gened, "credits": credits}
    if len(codes) >= 2:
        slot = {"type": "choose_one", "codes": codes, "credits": credits}
        if gened:
            slot["gen_ed"] = gened
        return slot
    if len(codes) == 1:
        slot = {"type": "course", "code": codes[0], "credits": credits}
        if gened:
            slot["gen_ed"] = gened
        return slot
    # No codes, no recognized keyword → treat as a generic gen-ed/elective slot.
    return {"type": "gen_ed", "category": gened, "credits": credits}


def parse_plangrid(html: str) -> list[dict]:
    """Parse the sc_plangrid table into an ordered list of semester dicts."""
    soup = BeautifulSoup(html.replace("\xa0", " "), "html.parser")
    table = soup.find("table", class_="sc_plangrid")
    if table is None:
        raise ValueError("no sc_plangrid table on page")

    # Bucket code cells by (year, term) using each cell's `header` attribute; pair
    # each with the credits in the matching hourscol cell of the same row.
    sems: dict[tuple[int, int], list[dict]] = {}
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        # Cells come in code/hours pairs across the two-column (Fall|Spring) layout.
        for i, td in enumerate(tds):
            cls = td.get("class", [])
            if "codecol" not in cls:
                continue
            header = " ".join(td.get("headers", []) or [td.get("header", "")])
            m = re.search(r"year(\d+)_Term(\d+)", header)
            if not m:
                continue
            year, term = int(m.group(1)), int(m.group(2))
            # credits = the next hourscol cell in this row
            credits = 0.0
            for nxt in tds[i + 1:]:
                if "hourscol" in nxt.get("class", []):
                    ct = _cell_text(nxt)
                    try:
                        credits = float(ct)
                    except ValueError:
                        credits = 0.0
                    break
            text = _cell_text(td)
            if not text:
                continue
            codes = _cell_codes(td, text)
            slot = _classify(text, codes, credits)
            sems.setdefault((year, term), []).append(slot)

    seasons = {0: "FA", 1: "SP"}
    out = []
    for (year, term) in sorted(sems):
        out.append({
            "year": year + 1,
            "term_season": seasons.get(term, "FA"),
            "credits": round(sum(float(s.get("credits", 0) or 0) for s in sems[(year, term)]), 1),
            "slots": sems[(year, term)],
        })
    return out


def scrape(program: dict) -> dict:
    """Scrape one program into a full template dict."""
    html = fetch(program["url"])
    semesters = parse_plangrid(html)
    total = round(sum(s["credits"] for s in semesters), 1)
    return {
        "program_name": program["program_name"],
        "subplan": program.get("subplan"),
        "catalog_year": program.get("catalog_year", "2024"),
        "degree": program.get("degree", ""),
        "total_credits": total,
        "source": program["url"],
        "scraped": True,
        "semesters": semesters,
    }


def _slug(program_name: str) -> str:
    # Drop dots first so "B.S." collapses to "bs" (not "b-s").
    return re.sub(r"[^a-z0-9]+", "-", program_name.lower().replace(".", "")).strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="parse + validate only, write nothing")
    ap.add_argument("--check-catalog", action="store_true", help="cross-check codes vs the catalog")
    args = ap.parse_args()

    known: set[str] = set()
    if args.check_catalog:
        from db import requirements_table  # noqa: local import (needs DynamoDB)
        from boto3.dynamodb.conditions import Key

        def _base(code):
            m = re.match(r"^([A-Z]+ \d+)[WHNMXYRS]?$", code.strip().upper())
            return m.group(1) if m else code.strip().upper()

        for prog in {p["program_name"] for p in PROGRAMS} | {"__GEN_ED__"}:
            resp = requirements_table.query(KeyConditionExpression=Key("program_name").eq(prog))
            rows = resp.get("Items", [])
            while "LastEvaluatedKey" in resp:
                resp = requirements_table.query(
                    KeyConditionExpression=Key("program_name").eq(prog),
                    ExclusiveStartKey=resp["LastEvaluatedKey"])
                rows.extend(resp.get("Items", []))
            known |= {_base(r.get("course_code", "")) for r in rows}

    ok, failed = 0, 0
    for prog in PROGRAMS:
        name = prog["program_name"]
        try:
            tpl = scrape(prog)
        except Exception as e:  # noqa: BLE001
            print(f"SCRAPE-FAIL {name}: {e!r}")
            failed += 1
            continue

        problems = validate_template(tpl)
        if args.check_catalog and known:
            def _b(code):
                m = re.match(r"^([A-Z]+ \d+)[WHNMXYRS]?$", code.strip().upper())
                return m.group(1) if m else code.strip().upper()
            missing = [c for c in pinned_course_codes(tpl)
                       if _b(c) not in known and c != "PSU 6"]
            if missing:
                problems.append(f"pinned courses not in catalog: {missing}")

        n_sem = len(tpl["semesters"])
        if problems:
            print(f"INVALID {name}: {n_sem} sems, {tpl['total_credits']}cr -> {problems}")
            failed += 1
            continue

        print(f"OK      {name}: {n_sem} sems, {tpl['total_credits']}cr")
        ok += 1
        if not args.dry_run:
            os.makedirs(_OUT_DIR, exist_ok=True)
            path = os.path.join(_OUT_DIR, f"{_slug(name)}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(tpl, f, indent=2, ensure_ascii=False)
            print(f"        wrote {os.path.relpath(path)}")

    print(f"\n{ok} valid, {failed} failed/invalid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
