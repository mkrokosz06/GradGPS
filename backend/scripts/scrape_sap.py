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
    python scripts/scrape_sap.py --options [--dry-run]  # one template per UP option grid

Only templates that pass validation are written — a bad scrape never goes live.
"""

import argparse
import collections
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from plan_templates import validate_template, fixed_codes, pinned_course_codes, slot_credits

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

# Programs whose bulletin page publishes SEVERAL suggested-plan grids (one per
# option/campus/pathway) on a single page.  The default one-table scrape (and
# `--all`) grabs only the FIRST grid, so an option student falls back to the
# wrong plan — a Forensic Chemistry student was scheduled against the Forensic
# Molecular Biology grid, surfacing phantom biology courses + a spurious 5th
# year.  Each entry pins a specific grid by the substrings of its `<h3.toggle>`
# heading and writes a subplan-tagged template (`subplan` MUST equal the value
# stored on the user record so load_template's exact-subplan match wins).
# University-Park grids only, per the UP-only template scope (docs/…-sap-hybrid).
SUBPLAN_PROGRAMS: list[dict] = [
    {"program_name": "Forensic Science, B.S.", "subplan": "Forensic Chemistry",
     "degree": "B.S.",
     "url": "https://bulletins.psu.edu/undergraduate/colleges/eberly-science/forensic-science-bs/",
     "heading": ["Forensic Chemistry Option:", "University Park"],
     # The bulletin's SUGGESTED-PLAN grid fills the biology requirement with the
     # BIOL 114/115 + 234/235W sequence, but the same bulletin's "Requirements
     # for the Major" table (which the audit uses, and which actually gates the
     # degree) prescribes BIOL 110 + BIOL 230W for ALL options.  Left as scraped,
     # those grid courses are never satisfiable (not real requirements) so the
     # timeline schedules them forever and never shows the real BIOL 230W.
     # Reconcile the slots to the authoritative requirement (net credits equal).
     "corrections": [
         {"replace": ["BIOL 114", "BIOL 115"],
          "with": {"type": "course", "code": "BIOL 110", "credits": 4.0}},
         {"replace": ["BIOL 234", "BIOL 235W"],
          "with": {"type": "course", "code": "BIOL 230W", "credits": 4.0}},
     ],
     # The grid schedules the option's advanced-chem electives as generic
     # "Supporting Course (consult your adviser)" cells; the concrete list lives
     # only in the bulletin's "Approved Supporting Courses" footnote. Stamp the
     # codes on so the picker + auto-satisfy work (pick 3, 9-11 cr).
     "supporting": {
         "label": "Approved Supporting Course",
         "codes": ["BMB 428", "CHEM 410", "CHEM 412", "CHEM 423W",
                   "CHEM 430", "CHEM 431W", "CHEM 450", "CHEM 452"],
     }},
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
    req = urllib.request.Request(url, headers={"User-Agent": "GradGPS-SAPScraper/1.0 (educational use; mkrokosz06@gmail.com)"})
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


_PAREN_RE = re.compile(r"\(([^()]+)\)")


def _family_groups(text: str, codes: list[str]) -> list[list[str]] | None:
    """Ordered course-code families from a '(A or B) or (C or D)' cell, else None.

    Smeal-style plans parenthesize alternative FAMILIES when one slot offers a
    pick per family across mirrored semesters — '(MATH 110 or MATH 140) or
    (SCM 200 or STAT 200)', with the semester's suggested family listed first.
    Only trusted when the parenthesized groups partition the cell's full code
    list exactly (a partial parenthesization returns None)."""
    fams: list[list[str]] = []
    for m in _PAREN_RE.finditer(text):
        grp = [f"{c.group(1)} {c.group(2)}" for c in _CODE_RE.finditer(m.group(1))]
        if grp:
            fams.append(grp)
    if len(fams) < 2:
        return None
    flat = [c for f in fams for c in f]
    if len(flat) != len(set(flat)) or set(flat) != {c.upper() for c in codes}:
        return None
    return fams


def _narrow_family_slots(semesters: list[dict]) -> None:
    """Split mirrored multi-family choose_one slots into one family per slot.

    A multi-family cell means 'take one course from EACH family, one family per
    semester, in either order' — the bulletin repeats the cell once per family.
    Left flat, the slots are wrong two ways: the UI shows the same 4-way choice
    twice, and the matcher would let two courses from ONE family (MATH 110 +
    MATH 140) satisfy both slots, never scheduling the other family.

    When a family-set's occurrence count equals its family count and each
    occurrence leads with a different family, narrow each slot to its
    first-listed family (semester 1 shows 'MATH 110 or MATH 140', semester 2
    'SCM 200 or STAT 200').  Any other shape — a one-off multi-family cell, a
    miscount — keeps the flat code list rather than guessing."""
    groups: dict[frozenset, list[dict]] = {}
    for sem in semesters:
        for slot in sem.get("slots", []):
            if slot.get("families"):
                key = frozenset(frozenset(f) for f in slot["families"])
                groups.setdefault(key, []).append(slot)
    for key, slots in groups.items():
        firsts = [frozenset(s["families"][0]) for s in slots]
        if len(slots) == len(key) and set(firsts) == key:
            for s in slots:
                s["codes"] = s["families"][0]
        for s in slots:
            del s["families"]


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
        slot = {"type": "pool", "ref": "business_breadth", "label": "Business Breadth Course", "credits": credits}
        if codes:
            # "BA 411 or a Business Breadth course" (Smeal): BA 411 fills it too.
            # Hand-restored in 6f6fea7 after this branch flattened it; now scraped.
            slot.update(label="BA 411 or a Business Breadth course" if codes == ["BA 411"] else text,
                        codes=codes)
        return slot
    # A department level-selection placeholder — "EDTHP 400 Level Selection",
    # "PLSC 400-Level" — means pick ANY course in that department at that level.
    # Without this branch the code regex reduces it to a literal course ("PLSC
    # 400", which may not even exist) repeated once per semester it appears in.
    m = re.search(r"\b([A-Z]{2,5})\s+(\d{3})[\s-]*[Ll]evel\b", text)
    if m:
        dept, level = m.group(1), int(m.group(2))
        return {"type": "pool", "ref": "dept_level", "dept": dept, "level": level,
                "label": f"{dept} {level}-Level Course", "credits": credits}
    # A departmental elective pool: a "NXX" course-number wildcard (ACCTG 4XX,
    # MKTG 4XX) or a "<Dept> Elective" label, optionally anchored by a real course.
    if re.search(r"\b\d?XX\b", text) or ("elective" in low and codes):
        slot = {"type": "pool", "ref": "major_elective", "label": text, "credits": credits}
        if codes:
            slot["codes"] = codes
        return slot
    # A "Supporting Course (consult your adviser)" cell — an advisor-approved
    # course from a program-specific pool whose members live only in a bulletin
    # footnote, never in the grid. Keep it a `pool` (NOT gen_ed, or a spare
    # gen-ed course would wrongly satisfy it and it would never schedule); a
    # SUBPLAN_PROGRAMS `supporting` spec stamps the concrete codes on afterward
    # (see _apply_supporting).
    if "supporting course" in low or (low.startswith("supporting") and not codes):
        slot = {"type": "pool", "ref": "supporting", "label": text, "credits": credits}
        if codes:
            # "PHYS 213 (or Supporting Course)", "Supporting Course (ACCTG 211 is
            # recommended)": the named course anchors the pool — offered by the
            # picker, and satisfies the slot if taken — without being required.
            slot["codes"] = codes
        return slot
    # A free-elective cell: bare "Elective"/"Electives", or any "… Elective …"
    # phrasing with no codes ("General Elective Course"). Without the broad
    # no-codes match these fall through to the default gen_ed return and get
    # soaked up by spare gen-ed courses instead of a real elective.
    if "elective" in low and not codes:
        # Only an unqualified elective is FREE — satisfied by any spare credits.
        # "Chemical Engineering Elective", "CMPEN Elective", "Technical Elective"
        # draw on a department list; typed free, a student's unrelated surplus
        # credits "completed" their technical electives.
        core = re.sub(r"\([^)]*\)|\bcourses?\b|\(s\)", " ", low)
        core = re.sub(r"[^a-z/ ]", " ", core).split()
        qualifiers = [w for w in core if w not in {"elective", "electives", "general", "free",
                                                   "or", "and", "a", "an", "see", "notes", "note"}]
        if qualifiers and not re.search(r"general education|gen ed|world cultures|minor|/", low):
            return _classify_placeholder(text, gened, credits, major=True)
        return {"type": "elective", "label": text or "Elective", "credits": credits}
    if "general education" in low or (gened and not codes):
        return {"type": "gen_ed", "category": gened, "credits": credits}
    if len(codes) >= 2:
        slot = {"type": "choose_one", "codes": codes, "credits": credits}
        fams = _family_groups(text, codes)
        if fams:
            slot["families"] = fams   # interim; consumed by _narrow_family_slots
        if gened:
            slot["gen_ed"] = gened
        return slot
    if len(codes) == 1:
        slot = {"type": "course", "code": codes[0], "credits": credits}
        if gened:
            slot["gen_ed"] = gened
        return slot
    return _classify_placeholder(text, gened, credits)


# A codeless grid cell that IS general education: a domain, the first-year
# seminar, cultures, health and wellness, integrative studies.
_GENED_LABEL = re.compile(
    r"general\s+ed|gen\s*ed\b|\b(?:GA|GH|GN|GS|GQ|GHW|GWS|US|IL)\b|first[\s-]*year|\bFYS\b"
    r"|health and (?:physical|wellness)|wellness|\bcultures?\b|knowledge domain|inter-?domain"
    r"|integrative|exploration|quantification|foundation", re.I)
# A Bachelor of Arts degree requirement (BA Fields, BA World Cultures, a foreign
# language) — neither general education nor the major.
_BA_LABEL = re.compile(
    r"\bB\.?\s?A\.?\s+(?:fields?|world|other|knowledge|requirement|course)|bachelor of arts"
    r"|world cultures|other cultures|foreign language|language level", re.I)
_LEVEL_LABEL = re.compile(r"\b(\d)(?:00|xx|XX)[\s-]*(?:or\s+\d00[\s-]*)?level\b|\blevel\s+(\d)00\b", re.I)


def _classify_placeholder(text: str, gened: str | None, credits: float,
                          major: bool = False) -> dict:
    """A cell with no course code and no keyword the branches above know.

    This used to fall through to a category-less gen-ed slot. But most such cells
    are MAJOR requirements — "400-Level HIST Course", "Option Course", "MATSE
    Specialization Course", "Application Focus Selection" (1,137 slots in 187
    templates) — and a category-less gen-ed slot is retired once the student's
    gen-eds are done, so real major coursework silently left the plan of every
    student far enough along. Only genuine gen-ed labels stay gen-ed."""
    label = re.sub(r"\s+", " ", re.sub(r"[\*#†‡§¶]+", "", text)).strip() or "Major Course"
    # A zero-credit cell is an instruction ("Enter the major before the end of
    # this semester…"), not coursework — keep the old, inert handling.
    if major:                                 # a qualified elective: always the major's
        return _scope({"type": "pool", "ref": "major_selection", "label": label,
                       "credits": credits}, text)
    if not credits:
        return {"type": "gen_ed", "category": gened, "credits": credits}
    # B.A. before gen-ed: "BA World Cultures" would otherwise read as gen-ed cultures.
    if _BA_LABEL.search(text):
        return {"type": "pool", "ref": "ba_requirement", "label": label, "credits": credits}
    if _GENED_LABEL.search(text):
        return {"type": "gen_ed", "category": gened, "credits": credits}
    slot = {"type": "pool",
            "ref": "application_focus" if "application focus" in text.lower() else "major_selection",
            "label": label, "credits": credits}
    return _scope(slot, text)


def _scope(slot: dict, text: str) -> dict:
    """Add the dept / level a placeholder's label names ("400-Level HIST Course")."""
    m = _LEVEL_LABEL.search(text)
    if m:
        slot["level"] = int(m.group(1) or m.group(2)) * 100
    depts = [w for w in re.findall(r"\b[A-Z]{2,5}\b", text) if w in _subjects()]
    if len(depts) == 1:                      # "400-Level HIST Course"; "HIST/GEOG" is ambiguous
        slot["dept"] = depts[0]
    return slot


_SUBJECTS: set[str] | None = None


def _subjects() -> set[str]:
    """Every PSU subject prefix (HIST, SOC, MATSE…), from the bulletin course list."""
    global _SUBJECTS
    if _SUBJECTS is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bulletin_courses.json")
        try:
            _SUBJECTS = {k.split()[0] for k in json.load(open(path, encoding="utf-8"))} - {"BA"}
        except Exception:
            _SUBJECTS = set()
    return _SUBJECTS


def parse_plangrid(html: str) -> list[dict]:
    """Parse the sc_plangrid table into an ordered list of semester dicts."""
    soup = BeautifulSoup(html.replace("\xa0", " "), "html.parser")
    table = soup.find("table", class_="sc_plangrid")
    if table is None:
        raise ValueError("no sc_plangrid table on page")

    # Bucket code cells by (year, term) using each cell's `header` attribute; pair
    # each with the credits in the matching hourscol cell of the same row.
    def _yt(td):
        header = td.get("header", "") or " ".join(td.get("headers", []) or [])
        m = re.search(r"year(\d+)_Term(\d+)", header)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        # Single-column variant: one column per YEAR, header "yearN undefinedcodecol"
        # (no Fall/Spring split). Use term = -1 as a "whole year" marker.
        m = re.search(r"year(\d+)\s+undefined", header)
        return (int(m.group(1)), -1) if m else None

    sems: dict[tuple[int, int], list[dict]] = {}
    for tr in table.select("tbody tr"):
        # Pair code and hours cells by their EXACT year/term header (not "next
        # cell") — rows where Fall and Spring hold different numbers of courses
        # would otherwise mis-pair credits.
        hours: dict[tuple[int, int], float] = {}
        code_cells: list[tuple[tuple[int, int], object]] = []
        for td in tr.find_all("td"):
            yt = _yt(td)
            if yt is None:
                continue
            cls = td.get("class", [])
            if "hourscol" in cls:
                mnum = re.search(r"\d+(?:\.\d+)?", _cell_text(td))
                if mnum:
                    hours[yt] = float(mnum.group(0))
            elif "codecol" in cls:
                code_cells.append((yt, td))
        for yt, td in code_cells:
            text = _cell_text(td)
            if not text:
                continue
            # Default to 3 when a course's credit cell is blank, variable, or a
            # footnoted "0" (e.g. a variable-credit thesis) — never leave a slot at
            # 0, which would desync the semester total from the per-slot total.
            credits = hours.get(yt) or 3.0
            slot = _classify(text, _cell_codes(td, text), credits)
            sems.setdefault(yt, []).append(slot)

    def _cr(s):
        return float(s.get("credits", 0) or 0)

    def _emit(year, term, slots):
        # Term index → season. CourseLeaf plans that include a summer term use
        # Term2 (Fall=0, Spring=1, Summer=2); mislabeling it Fall creates a
        # duplicate-Fall semester and dumps the summer internship/field course
        # into a phantom Fall.
        return {"year": year + 1, "term_season": {0: "FA", 1: "SP", 2: "SU"}.get(term, "FA"),
                "credits": round(sum(_cr(s) for s in slots), 1), "slots": slots}

    # Single-column (year-level) plan: split each year's ordered course list into
    # two ~half-credit Fall/Spring semesters, preserving order.
    if any(term == -1 for (year, term) in sems):
        out = []
        for year in sorted({y for (y, _) in sems}):
            slots = sems[(year, -1)]
            half = sum(_cr(s) for s in slots) / 2
            acc, fall, spring = 0.0, [], []
            for s in slots:
                if acc < half:
                    fall.append(s); acc += _cr(s)
                else:
                    spring.append(s)
            for term, group in ((0, fall), (1, spring)):
                if group:
                    out.append(_emit(year, term, group))
    else:
        out = [_emit(year, term, sems[(year, term)]) for (year, term) in sorted(sems)]

    _narrow_family_slots(out)
    _normalize_breadth(out)
    return out


def _normalize_breadth(semesters: list[dict]) -> None:
    """Smeal's Business Breadth is ONE two-piece sequence — two plain breadth
    slots — beside a "BA 411 or a Business Breadth course" slot. Grids print the
    trio inconsistently (Finance: two "BA 411 (or Business Breadth Course)" cells
    and one plain), so make the first ones plain until there are two
    (docs/business-breadth.md; hand-applied in 6f6fea7, now part of the scrape)."""
    slots = [s for sem in semesters for s in sem["slots"]
             if s.get("type") == "pool" and s.get("ref") == "business_breadth"]
    plain = sum(1 for s in slots if not s.get("codes"))
    for s in slots:
        if plain >= 2 or len(slots) < 3:
            break
        if s.get("codes"):
            s.pop("codes")
            s["label"] = "Business Breadth Course"
            plain += 1


_SITEMAP ="https://bulletins.psu.edu/sitemap.xml"

# UP resident-instruction college path segments (branch campuses excluded — this
# app is University Park only; see routers.programs.is_up_program).
_UP_COLLEGES = {
    "agricultural-sciences", "arts-architecture", "bellisario-communications",
    "earth-mineral-sciences", "eberly-science", "education", "engineering",
    "health-human-development", "information-sciences-technology", "intercollege",
    "liberal-arts", "nursing", "smeal-business", "division-undergraduate-studies",
}

_PROGRAM_URL_RE = re.compile(r"/undergraduate/colleges/([a-z0-9-]+)/([a-z0-9-]+)/?$")


def _base_code(code: str) -> str:
    m = re.match(r"^([A-Z]+ \d+)[WHNMXYRS]?$", code.strip().upper())
    return m.group(1) if m else code.strip().upper()


def _page_name(soup) -> str:
    """The program's full name (with college parenthetical) from the page title —
    which equals the catalog program_name, e.g. 'Accounting, B.S. (Business)'."""
    t = soup.title.get_text(strip=True) if soup.title else ""
    return re.sub(r"\s*\|\s*Penn State\s*$", "", t).strip()


def _degree(name: str) -> str:
    m = re.search(r",\s*([A-Z][A-Za-z.]*\.)\s*(?:\(|$)", name)
    return m.group(1) if m else ""


def scrape_html(html: str, program_name: str, degree: str, url: str) -> dict:
    semesters = parse_plangrid(html)   # raises if no sc_plangrid table
    return {
        "program_name": program_name,
        "subplan": None,
        "catalog_year": "2024",
        "degree": degree or _degree(program_name),
        "total_credits": round(sum(s["credits"] for s in semesters), 1),
        "source": url,
        "scraped": True,
        "semesters": semesters,
    }


def scrape(program: dict) -> dict:
    """Scrape one program (from the PROGRAMS list) into a full template dict."""
    return scrape_html(fetch(program["url"]), program["program_name"],
                       program.get("degree", ""), program["url"])


def _grid_by_heading(html: str, must_contain: list[str]) -> tuple[str, str]:
    """(grid HTML, heading text) of the sc_plangrid whose preceding `<h3.toggle>`
    heading contains ALL of `must_contain` (case-insensitive).  Raises if none or
    more than one matches — an ambiguous pin should fail loudly, not guess."""
    soup = BeautifulSoup(html.replace("\xa0", " "), "html.parser")
    hits: list[tuple[str, str]] = []
    for t in soup.find_all("table", class_="sc_plangrid"):
        h = t.find_previous(lambda tag: tag.name == "h3" and "toggle" in (tag.get("class") or []))
        htext = h.get_text(" ", strip=True) if h else ""
        if all(s.lower() in htext.lower() for s in must_contain):
            hits.append((str(t), htext))
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} plangrids match heading {must_contain} (want exactly 1)")
    return hits[0]


def _apply_corrections(semesters: list[dict], corrections: list[dict]) -> None:
    """Reconcile scraped grid slots to the authoritative Requirements table where
    a bulletin's suggested plan disagrees with its own major requirements (see the
    `corrections` note in SUBPLAN_PROGRAMS).  Each correction removes the slots
    whose course `code` is in `replace` and inserts `with` at the first one's
    position.  Raises if a `replace` code isn't found — a silent no-op would let
    a stale correction rot unnoticed after a bulletin re-scrape."""
    def _codes(slot):
        return [slot.get("code")] if slot.get("code") else slot.get("codes", [])
    for corr in corrections or []:
        want = set(corr["replace"])
        for sem in semesters:
            idxs = [i for i, s in enumerate(sem["slots"])
                    if want & set(_codes(s))]
            if idxs:
                sem["slots"][idxs[0]] = dict(corr["with"])
                for i in reversed(idxs[1:]):
                    del sem["slots"][i]
                sem["credits"] = round(sum(slot_credits(s) for s in sem["slots"]), 1)
                break
        else:
            raise ValueError(f"correction target {sorted(want)} not found in grid")


def _apply_supporting(semesters: list[dict], supporting: dict | None) -> None:
    """Stamp the program's footnote-sourced 'Approved Supporting Courses' codes
    onto the generic `supporting` pool slots _classify emitted (the grid names
    the pool only as 'Supporting Course', never its members).  Raises if the spec
    is present but no supporting slot exists — a stale spec shouldn't rot silently
    after a bulletin re-scrape."""
    if not supporting:
        return
    hit = False
    for sem in semesters:
        for slot in sem["slots"]:
            if slot.get("type") == "pool" and slot.get("ref") == "supporting":
                slot["codes"] = list(supporting["codes"])
                if supporting.get("label"):
                    slot["label"] = supporting["label"]
                hit = True
    if not hit:
        raise ValueError("supporting spec set but no 'supporting' pool slot in grid")


def scrape_subplan(spec: dict) -> dict:
    """Scrape a single option/campus grid off a multi-plan page into a
    subplan-tagged template (see SUBPLAN_PROGRAMS)."""
    grid_html, heading = _grid_by_heading(fetch(spec["url"]), spec["heading"])
    semesters = parse_plangrid(grid_html)
    _apply_corrections(semesters, spec.get("corrections"))
    _apply_supporting(semesters, spec.get("supporting"))
    return {
        "program_name": spec["program_name"],
        "subplan": spec["subplan"],
        "catalog_year": "2024",
        "degree": spec.get("degree") or _degree(spec["program_name"]),
        "total_credits": round(sum(s["credits"] for s in semesters), 1),
        "source": spec["url"],
        "source_plan": heading,
        "scraped": True,
        "semesters": semesters,
    }


def discover_up_urls() -> list[str]:
    """All University Park program-page URLs from the bulletin sitemap."""
    xml = fetch(_SITEMAP)
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    out = []
    for u in urls:
        m = _PROGRAM_URL_RE.search(u)
        if m and m.group(1) in _UP_COLLEGES:
            out.append(u)
    return sorted(set(out))


def _load_catalog():
    """(UP program_name set, base-code set catalogued anywhere) for matching + gate."""
    from db import requirements_table  # noqa: local import (needs DynamoDB)
    sys.path.insert(0, os.path.dirname(_OUT_DIR))
    from routers.programs import is_up_program

    names: set[str] = set()
    known: set[str] = set()
    resp = requirements_table.scan(ProjectionExpression="program_name, course_code")
    rows = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.scan(ProjectionExpression="program_name, course_code",
                                       ExclusiveStartKey=resp["LastEvaluatedKey"])
        rows.extend(resp.get("Items", []))
    for r in rows:
        pn = r.get("program_name", "")
        if pn and pn != "__GEN_ED__" and is_up_program(pn):
            names.add(pn)
        if r.get("course_code"):
            known.add(_base_code(r["course_code"]))
    return names, known


def _sanity_problems(tpl: dict) -> list[str]:
    """Reject grids that don't look like a real 4-year degree plan."""
    problems = []
    n = len(tpl["semesters"])
    if not (6 <= n <= 12):
        problems.append(f"implausible semester count: {n}")
    # Up to 170 covers 5-year professional degrees (B.Arch, B.A.E.).
    if not (100 <= tpl["total_credits"] <= 170):
        problems.append(f"implausible total credits: {tpl['total_credits']}")
    return problems


def _slug(program_name: str) -> str:
    # Drop dots first so "B.S." collapses to "bs" (not "b-s").
    return re.sub(r"[^a-z0-9]+", "-", program_name.lower().replace(".", "")).strip("-")


def _validate(tpl: dict, known: set[str]) -> list[str]:
    problems = validate_template(tpl) + _sanity_problems(tpl)
    if known:
        # The requirements catalog doesn't list EVERY PSU course — first-year
        # seminars (LA 83), language sequences (SPAN 1/2/3), and gen-ed-only
        # courses live elsewhere, so language/area-studies majors legitimately pin
        # many un-catalogued courses. Only an OVERWHELMING unknown fraction signals
        # a systematic parse failure (a mis-read subject code), which is the gate.
        pinned = [c for c in pinned_course_codes(tpl) if c != "PSU 6"]
        missing = [c for c in pinned if _base_code(c) not in known]
        if pinned and len(missing) / len(pinned) > 0.75:
            problems.append(
                f"{len(missing)}/{len(pinned)} pinned courses not in catalog "
                f"(likely parse error): {sorted(missing)[:6]}")
    return problems


def _write(tpl: dict):
    os.makedirs(_OUT_DIR, exist_ok=True)
    slug = _slug(tpl["program_name"])
    if tpl.get("subplan"):
        slug = f"{slug}-{_slug(tpl['subplan'])}"   # keep base + option variants distinct
    path = os.path.join(_OUT_DIR, f"{slug}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tpl, f, indent=2, ensure_ascii=False)
    return path


def _run_all(dry_run: bool):
    """Discover every UP program page, scrape those with a plan grid, match to the
    catalog, validate, and write the ones that pass."""
    up_names, known = _load_catalog()
    urls = discover_up_urls()
    print(f"discovered {len(urls)} UP program URLs; catalog has {len(up_names)} UP programs\n")

    ok = skipped = unmatched = invalid = errors = 0
    for i, url in enumerate(urls, 1):
        try:
            html = fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   fetch {url}: {e!r}"); errors += 1; continue
        soup = BeautifulSoup(html.replace("\xa0", " "), "html.parser")
        name = _page_name(soup)
        if "sc_plangrid" not in html:
            skipped += 1; continue                        # no SAP on this page
        # Bachelor's degrees only — skip associate (A.S./A.ENGT.) 2-year plans.
        degree = _degree(name)
        if degree and not degree.startswith("B"):
            skipped += 1; continue
        if name not in up_names:
            unmatched += 1
            print(f"  UNMATCHED {name!r}  ({url.split('/')[-2]})")
            continue
        try:
            tpl = scrape_html(html, name, _degree(name), url)
        except Exception as e:  # noqa: BLE001
            print(f"  ERR   parse {name}: {e!r}"); errors += 1; continue
        problems = _validate(tpl, known)
        if problems:
            invalid += 1
            print(f"  INVALID {name}: {len(tpl['semesters'])}sem {tpl['total_credits']}cr -> {problems[:2]}")
            continue
        ok += 1
        print(f"  OK      {name}: {len(tpl['semesters'])}sem {tpl['total_credits']}cr"
              + ("" if dry_run else f"  -> {os.path.basename(_write(tpl))}"))

    print(f"\n{ok} written, {invalid} invalid, {unmatched} unmatched, "
          f"{skipped} no-plan, {errors} errors  (of {len(urls)} pages)")
    return 0


# ── Option grids ─────────────────────────────────────────────────────────────
#
# A bulletin page for a major with options publishes one plan grid PER OPTION
# ("Biology Teaching Option: Secondary Education, B.S. at University Park
# Campus"). `--all` keeps only the first, and load_template() fell back to it
# for every option — so a Social Studies teaching student was scheduled the
# Biology Teaching plan. `--options` writes one subplan-tagged template per
# University Park option grid, named with the catalog's own option name (the
# value the student's profile stores), and cross-checks every match against
# that option's requirement group before writing it.

_OPTION_HEAD = re.compile(r"^(.+?)\s+Option\s*:\s*(.*)$", re.I)
_OPTION_STOP = {"option", "focused", "the", "of", "in", "and", "to", "for", "a"}


def parse_grid_heading(heading: str) -> tuple[str | None, str]:
    """'Biology Teaching Option: Secondary Education, B.S. at University Park
    Campus' -> ('Biology Teaching', 'University Park Campus')."""
    heading = re.sub(r"\s+", " ", heading or "").strip()
    option, rest = None, heading
    m = _OPTION_HEAD.match(heading)
    if m:
        option, rest = m.group(1).strip(), m.group(2)
    campus = rest.split(" at ", 1)[1].strip() if " at " in rest else ""
    return option, campus


def is_up_grid(campus: str) -> bool:
    """A grid University Park students follow: UP-only, UP-and-elsewhere, or no
    campus named at all. It must START at University Park — "Starting at Berks
    Campus and Ending at University Park Campus" is a 2+2 transfer plan."""
    return not campus or campus.lower().startswith("university park")


def _option_tokens(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (name or "").lower().replace("&", " and "))
    out = []
    for w in words:
        if w in _OPTION_STOP or w.isdigit():
            continue
        if w.endswith("ies"):
            w = w[:-3] + "y"                     # studies -> study
        out.append(w)
    return out


def _token_eq(a: str, b: str) -> bool:
    """Same word up to inflection: biology/biological, computation/computational,
    math/mathematics, resource/resources."""
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5]:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and long_.startswith(short)


def match_option(grid_option: str, subplans: list[str]) -> str | None:
    """The catalog subplan a grid's option heading names, or None.

    PSU words the two differently — 'Biology Teaching' / 'Biological Science
    Teaching', 'Math' / 'Mathematics 4-8', 'Graduate Studies' / 'Graduate
    Study' — so this matches on word containment: every word of the shorter
    name must appear (up to inflection) in the longer. A match must be UNIQUE;
    an ambiguous one returns None rather than guess (the caller reports it).
    """
    g = _option_tokens(grid_option)
    if not g:
        return None
    hits = []
    for sp in subplans:
        s = _option_tokens(sp)
        if not s:
            continue
        short, long_ = (g, s) if len(g) <= len(s) else (s, g)
        if all(any(_token_eq(w, x) for x in long_) for w in short):
            # Prefer the closest: fewest unmatched words on the longer side.
            hits.append((len(long_) - len(short), sp))
    if not hits:
        return None
    hits.sort()
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        return None
    return hits[0][1]


def is_exact_option_match(grid_option: str, subplan: str) -> bool:
    """Same words on both sides (up to inflection) — the grid is headed with the
    option's own name, so no course evidence is needed to trust it."""
    g, s = _option_tokens(grid_option), _option_tokens(subplan)
    return len(g) == len(s) and all(any(_token_eq(w, x) for x in s) for w in g)


def collapse_renamed_duplicates(semesters: list[dict]) -> list[tuple[str, str]]:
    """A grid that lists a course under BOTH its old and new number (LA 83 in
    one cohort-year cell, LA 283 in another) schedules the same course twice,
    and the matcher's one-course-one-slot rule leaves the second forever
    unsatisfied. Keep the first slot under the current code, drop the other.
    This is the LA 83 / LA 283 fix (0a16a24) made part of the scrape, so a
    re-scrape can't reintroduce it."""
    from audit_engine import _MANUAL_RENAME_PAIRS
    collapsed = []
    for old, new in _MANUAL_RENAME_PAIRS:
        spots = [(si, i) for si, sem in enumerate(semesters)
                 for i, slot in enumerate(sem["slots"])
                 if slot.get("type") == "course" and _base_code(slot.get("code", "")) in (old, new)]
        if len(spots) < 2:
            continue
        (fs, fi), rest = spots[0], spots[1:]
        semesters[fs]["slots"][fi]["code"] = new
        for si, i in sorted(rest, reverse=True):
            del semesters[si]["slots"][i]
        for sem in semesters:
            sem["credits"] = round(sum(slot_credits(s) for s in sem["slots"]), 1)
        collapsed.append((old, new))
    return collapsed


def option_group_codes(rows: list[dict], subplan: str) -> set[str]:
    """Course codes of the catalog's own requirement group(s) for one option —
    the same substring rule routers/audit._filter_rows uses to pick them."""
    sl = subplan.lower()
    return {_base_code(r["course_code"]) for r in rows
            if sl in r.get("requirement_group", "").lower()
            and " at " not in r.get("requirement_group", "").lower()
            and r.get("course_code")}


def best_option_by_courses(template_codes: set[str], option_codes: dict[str, set[str]]) -> list[str]:
    """Options ranked by how much of each option's OWN course list the plan
    contains. The name matcher's independent witness: a plan for Biology
    Teaching must overlap the Biological Science Teaching group more than any
    other option's group."""
    # Only courses UNIQUE to one option discriminate: options share most of their
    # lists (Chemistry Teaching's group carries biology too), and scoring shared
    # courses crowned whichever option had the shortest list.
    scored = []
    for sp, codes in option_codes.items():
        others = set().union(*(c for o, c in option_codes.items() if o != sp)) if len(option_codes) > 1 else set()
        own = codes - others
        if own:
            scored.append((len(template_codes & own), sp))
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return []                               # no discriminating signal: can't rank
    return [sp for score, sp in scored if score > 0]


def page_option_codes(html: str) -> dict[str, set[str]]:
    """{option name: course codes} from the page's own Program Requirements tab —
    each "French Teaching Option (36 credits)" heading to the next heading.

    A witness that shares nothing with the catalog: the catalog's option groups
    carry every scrape bug the loader has had (Biology's are bloated with
    duplicates, World Languages' route everything to ESL), while this reads the
    page directly. Course codes come from CourseLeaf's course links."""
    soup = BeautifulSoup(html.replace("\xa0", " "), "html.parser")
    box = soup.find(id="programrequirementstextcontainer")
    if not box:
        return {}
    out: dict[str, set[str]] = {}
    current = None
    for el in box.descendants:
        name = getattr(el, "name", None)
        if name in ("h2", "h3", "h4", "h5", "h6"):
            text = el.get_text(" ", strip=True)
            m = re.match(r"(.+?)\s+Option\b", text)
            current = m.group(1).strip() if m else None
            if current:
                out.setdefault(current, set())
        elif name == "a" and current:
            m = re.search(r"[?&]P=([A-Z][A-Z-]{1,6})%20(\d{1,3}[A-Z]?)", el.get("href", ""))
            if m:
                out[current].add(_base_code(f"{m.group(1)} {m.group(2)}"))
    return out


def _subplans_for(program: str) -> list[str]:
    from routers.audit import get_subplans
    return get_subplans(program)["subplans"]


def _program_rows(program: str) -> list[dict]:
    from db import requirements_table
    from boto3.dynamodb.conditions import Key
    rows, kw = [], {"KeyConditionExpression": Key("program_name").eq(program)}
    while True:
        r = requirements_table.query(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            return rows
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def build_option_templates(program: str, url: str, html: str, subplans: list[str],
                           rows: list[dict], known: set[str]) -> tuple[list[dict], list[str]]:
    """Every University Park option grid on one page as a subplan template, plus
    a report line for each grid or option that could not be placed."""
    soup = BeautifulSoup(html.replace("\xa0", " "), "html.parser")
    grids = []
    for t in soup.find_all("table", class_="sc_plangrid"):
        h = t.find_previous(lambda tag: tag.name == "h3" and "toggle" in (tag.get("class") or []))
        heading = h.get_text(" ", strip=True) if h else ""
        option, campus = parse_grid_heading(heading)
        if option and is_up_grid(campus):
            grids.append((option, heading, str(t)))
    if len({o for o, _, _ in grids}) < 2:
        return [], []
    # Courses in more than one option's plan (every Biology plan takes CHEM
    # 202/203) can't tell the plans apart, so the witnesses only see the rest.
    plan_sets = [{_base_code(c) for c in fixed_codes({"semesters": parse_plangrid(g)})}
                 for _, _, g in grids]
    seen = collections.Counter(c for codes in plan_sets for c in codes)
    shared = {c for c, n in seen.items() if n > 1}

    manual = {s["subplan"] for s in SUBPLAN_PROGRAMS if s["program_name"] == program}
    option_codes = {sp: option_group_codes(rows, sp) for sp in subplans}
    # The page's own option sections, keyed by the catalog subplan they name.
    page_codes: dict[str, set[str]] = {}
    for section, codes in page_option_codes(html).items():
        sp = next((s for s in subplans if is_exact_option_match(section, s)), None)
        if sp:
            page_codes[sp] = codes
    out, report, taken = [], [], set()
    for option, heading, grid_html in grids:
        sp = match_option(option, subplans)
        if sp is None:
            report.append(f"no selectable option for grid {option!r}")
            continue
        if sp in taken:
            report.append(f"second grid for {sp!r} ignored: {heading!r}")
            continue
        taken.add(sp)
        if sp in manual:
            continue                                  # hand-pinned in SUBPLAN_PROGRAMS
        semesters = parse_plangrid(grid_html)
        collapse_renamed_duplicates(semesters)
        tpl = {
            "program_name": program, "subplan": sp, "catalog_year": "2024",
            "degree": _degree(program),
            "total_credits": round(sum(s["credits"] for s in semesters), 1),
            "source": url, "source_plan": heading, "scraped": True,
            "semesters": semesters,
        }
        problems = _validate(tpl, known)
        # A grid headed with the option's own name needs no second opinion. A
        # REWORDED match ('Biology Teaching' for 'Biological Science Teaching')
        # needs its courses to agree: accepted if either witness — the page's
        # own option sections, or the catalog's option groups — ranks it first,
        # or if neither can tell the options apart; rejected if a witness points
        # at another option and none backs it.
        if not is_exact_option_match(option, sp):
            plan_codes = {_base_code(c) for c in fixed_codes(tpl)} - shared
            votes = [best_option_by_courses(plan_codes, page_codes),
                     best_option_by_courses(plan_codes, option_codes)]
            firsts = [v[0] for v in votes if v]
            if firsts and sp not in firsts:
                problems.append(f"reworded match {option!r}->{sp!r} but its courses "
                                f"point at {firsts[0]!r}")
        if problems:
            report.append(f"INVALID {sp!r}: {problems[:2]}")
            continue
        out.append(tpl)
    for sp in subplans:
        if sp not in taken:
            report.append(f"option {sp!r} has no plan grid (falls back to the audit-driven planner)")
    return out, report


def _slot_shape(semesters: list[dict]) -> list[list]:
    return [[s.get("code") or s.get("codes") or s.get("ref") or s.get("category")
             for s in sem["slots"]] for sem in semesters]


def _general_base(program: str, base: dict, html: str, known: set[str]) -> dict | None:
    """The base template (a student who picked no option) of an option major
    should be its "General …" grid when the page has one no student can select —
    not whichever option happened to come first (Biology's base was Ecology).

    Only replaces a base that is still exactly the scrape of the page's first
    grid, so a hand-corrected base is never overwritten."""
    soup = BeautifulSoup(html.replace("\xa0", " "), "html.parser")
    grids = []
    for t in soup.find_all("table", class_="sc_plangrid"):
        h = t.find_previous(lambda tag: tag.name == "h3" and "toggle" in (tag.get("class") or []))
        heading = h.get_text(" ", strip=True) if h else ""
        option, campus = parse_grid_heading(heading)
        if option and is_up_grid(campus):
            grids.append((option, heading, str(t)))
    subplans = _subplans_for(program)
    general = [g for g in grids if g[0].lower().startswith("general")
               and match_option(g[0], subplans) is None]
    if len(general) != 1 or grids[0][0] == general[0][0]:
        return None
    first = parse_plangrid(grids[0][2])
    collapse_renamed_duplicates(first)
    if _slot_shape(first) != _slot_shape(base["semesters"]):
        return None                                    # hand-edited: leave it alone
    semesters = parse_plangrid(general[0][2])
    collapse_renamed_duplicates(semesters)
    tpl = dict(base, semesters=semesters, source_plan=general[0][1],
               total_credits=round(sum(s["credits"] for s in semesters), 1))
    return None if _validate(tpl, known) else tpl


def _run_options(dry_run: bool) -> int:
    _, known = _load_catalog()
    written = 0
    for f in sorted(os.listdir(_OUT_DIR)):
        base = json.load(open(os.path.join(_OUT_DIR, f), encoding="utf-8"))
        if base.get("subplan"):
            continue
        program = base["program_name"]
        html = fetch(base["source"])
        tpls, report = build_option_templates(
            program, base["source"], html, _subplans_for(program), _program_rows(program), known)
        if not tpls and not report:
            continue
        print(f"{program}")
        general = _general_base(program, base, html, known)
        if general:
            dest = "" if dry_run else f"  -> {os.path.basename(_write(general))}"
            print(f"  BASE now the {general['source_plan']!r} grid{dest}")
        for tpl in tpls:
            written += 1
            dest = "" if dry_run else f"  -> {os.path.basename(_write(tpl))}"
            print(f"  OK   {tpl['subplan']}: {len(tpl['semesters'])}sem {tpl['total_credits']}cr{dest}")
        for line in report:
            print(f"  --   {line}")
    print(f"\n{written} option templates {'valid (dry run)' if dry_run else 'written'}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="parse + validate only, write nothing")
    ap.add_argument("--check-catalog", action="store_true", help="cross-check codes vs the catalog")
    ap.add_argument("--all", action="store_true", help="discover + scrape every UP major from the sitemap")
    ap.add_argument("--options", action="store_true",
                    help="write one subplan template per University Park option grid")
    args = ap.parse_args()

    if args.all:
        return _run_all(args.dry_run)
    if args.options:
        return _run_options(args.dry_run)

    known: set[str] = set()
    if args.check_catalog:
        _, known = _load_catalog()

    ok, failed = 0, 0
    jobs = ([(p["program_name"], lambda p=p: scrape(p)) for p in PROGRAMS]
            + [(f"{s['program_name']} [{s['subplan']}]", lambda s=s: scrape_subplan(s))
               for s in SUBPLAN_PROGRAMS])
    for name, do in jobs:
        try:
            tpl = do()
        except Exception as e:  # noqa: BLE001
            print(f"SCRAPE-FAIL {name}: {e!r}"); failed += 1; continue
        problems = _validate(tpl, known)
        if problems:
            print(f"INVALID {name}: {len(tpl['semesters'])} sems, {tpl['total_credits']}cr -> {problems}")
            failed += 1; continue
        print(f"OK      {name}: {len(tpl['semesters'])} sems, {tpl['total_credits']}cr")
        ok += 1
        if not args.dry_run:
            print(f"        wrote {os.path.relpath(_write(tpl))}")

    print(f"\n{ok} valid, {failed} failed/invalid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
