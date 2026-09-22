"""
Penn State Undergraduate Major Requirements Scraper
Scrapes bulletins.psu.edu for all University Park undergraduate programs
and their course requirements. Outputs Excel + TXT files.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import time
import re
import os
import json

BASE_URL = "https://bulletins.psu.edu"

# Authoritative course titles, so a combo row can be split into its real courses
# instead of guessing where one title ends and the next begins ("Biology: Basic
# Concepts and Biodiversity" legitimately contains " and ").
_BULLETIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "bulletin_courses.json")
try:
    with open(_BULLETIN_PATH, encoding="utf-8") as _f:
        BULLETIN = json.load(_f)
except Exception:
    BULLETIN = {}

# Course code as it appears in a CourseLeaf code cell.
#
# A few PSU subject prefixes contain a hyphen — "A-I" (Artificial Intelligence)
# is the one that bites, because A-I 100 is one of the seven ways to satisfy
# ETI's intro requirement and a plain [A-Z]{2,6} cannot see it, so the pool
# silently offered six options instead of seven. Hyphenated prefixes are allowed
# as long as the whole prefix is still at least two letters.
_CODE_IN_CELL_WIDE = re.compile(
    r"\b([A-Z]{2,6}(?:-[A-Z]{1,6})?|[A-Z](?:-[A-Z]){1,3})\s{0,2}(\d{1,3}[A-Z]?)\b"
)


def _code_ok(dept, num):
    """A 3-digit code is accepted as before.  A 1-2 digit code (ENGL 15, SOC 1,
    SPAN 3 -- 608 of the bulletin's 9,479 courses) is accepted only if the
    bulletin actually lists it, so a bare number in prose cannot invent one."""
    digits = "".join(ch for ch in num if ch.isdigit())
    if len(digits) >= 3:
        return True
    return (dept + " " + num) in BULLETIN


class _FilteredCodeRe:
    """Drop-in for the old _CODE_IN_CELL: same API, bulletin-gated short codes."""

    def finditer(self, text):
        for m in _CODE_IN_CELL_WIDE.finditer(text):
            if _code_ok(m.group(1), m.group(2)):
                yield m

    def search(self, text):
        for m in self.finditer(text):
            return m
        return None


_CODE_IN_CELL = _FilteredCodeRe()
HEADERS = {
    "User-Agent": "GradGPS-CatalogScraper/1.0 (educational use; mkrokosz06@gmail.com)"
}

# Global counter for unique pair group IDs across all programs
_pair_counter = [0]

def _next_pair_id():
    """Return a new globally-unique integer ID for an OR-alternative pair."""
    _pair_counter[0] += 1
    return _pair_counter[0]

def get_soup(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return BeautifulSoup(r.text, "lxml")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"  !! Failed: {url} — {e}")
                return None


# ── STEP 1: Get all undergraduate programs ──────────────────────────────────

def get_all_programs():
    print("Fetching program index from /programs/ ...")
    soup = get_soup(f"{BASE_URL}/programs/")
    programs = []
    if not soup:
        return programs

    seen = set()

    # Each program link is inside an <a> tag — get ONLY the link text,
    # not surrounding navigation. The link itself is the program name.
    for link in soup.find_all("a", href=True):
        href = link["href"]
        # Must match /undergraduate/colleges/[college]/[program]/
        if not re.match(r"^/undergraduate/colleges/[^/]+/[^/]+/?$", href):
            continue
        full_url = BASE_URL + href
        if full_url in seen:
            continue
        seen.add(full_url)

        # Clean name: only take the direct text of this <a>, strip trailing junk
        name = link.get_text(" ", strip=True)
        # Remove any text after common separators that indicate navigation bleed
        name = re.split(r"(?:Baccalaureate|Undergraduate|Graduate|Certificate|Minor|Penn State|University College)", name)[0].strip()
        name = re.sub(r"\s+", " ", name).strip(" ,")

        parts = href.strip("/").split("/")
        college_slug = parts[2] if len(parts) > 2 else "unknown"
        college = college_slug.replace("-", " ").title()

        programs.append({
            "name": name,
            "college": college,
            "college_slug": college_slug,
            "url": full_url
        })

    print(f"  Found {len(programs)} programs")
    return programs


# ── STEP 2: Scrape requirements for one program ──────────────────────────────

def scrape_program_requirements(program):
    soup = get_soup(program["url"])
    if not soup:
        return [], {}

    rows = []

    # ── Program metadata ──
    h1 = soup.find("h1")
    full_title = h1.get_text(strip=True) if h1 else program["name"]

    # Detect degree type
    degree = "N/A"
    for d in ["B.S.", "B.A.", "B.F.A.", "B.Arch.", "B.Des.", "B.Mus.", "B.Phil.", "B.Hum.", "B.Ed."]:
        if d in full_title:
            degree = d
            break
    if degree == "N/A":
        for d in ["Minor", "Certificate", "Associate"]:
            if d in full_title:
                degree = d
                break

    # Detect campus
    campus = "University Park"
    campus_indicators = ["Abington", "Altoona", "Behrend", "Berks", "Brandywine",
                         "DuBois", "Fayette", "Greater Allegheny", "Harrisburg",
                         "Hazleton", "Lehigh Valley", "Mont Alto", "New Kensington",
                         "Schuylkill", "Shenango", "Wilkes-Barre", "Worthington",
                         "York", "World Campus"]
    for c in campus_indicators:
        if c.lower() in full_title.lower() or c.lower() in program["url"].lower():
            campus = c
            break

    # ── Find the requirements tab content ──
    # PSU bulletin uses tab structure; look for the program requirements section
    req_content = None

    # Try common content containers
    for selector in [
        {"id": re.compile(r"requirementstab", re.I)},
        {"class": re.compile(r"(sc_page_content|program-requirements|tab-pane)", re.I)},
    ]:
        req_content = soup.find("div", selector)
        if req_content:
            break

    if not req_content:
        # Fall back to the whole page body
        req_content = soup.find("body") or soup

    # ── Parse requirement groups and courses ──
    current_group      = "General Requirements"
    current_group_type = "required"
    current_threshold  = None   # N for choose_credits or choose_courses

    # ── Pool identity ────────────────────────────────────────────────────────
    # A CourseLeaf section routinely holds SEVERAL independent pools, each
    # introduced by its own "Select N credits from the following:" comment row
    # and each listing its members in a <div class="blockindent">.  ETI's
    # "Additional Courses" has six.  Tracking only (group, type, threshold) —
    # which is all the audit engine had — merged every same-threshold pool in a
    # section into one, so a single ENGL 15 satisfied four separate 3-credit
    # requirements and CYBER 100 / IST 140 / the speech pool vanished from the
    # plan entirely.  `pool_seq` numbers the pools within a section so the audit
    # can tell them apart; rows without one bucket as None, i.e. exactly the
    # previous behaviour.
    current_pool_seq   = 0       # 0 = not in a pool
    pool_open          = False
    pool_indent_scoped = False   # members marked by <div class="blockindent">?
    pool_pending       = False   # opened by a comment row, no indented member yet
    heading_group_type = "required"
    heading_threshold  = None

    def close_pool():
        """Leave the current pool and fall back to the SECTION's own type.

        Without this a pool near the top of a table leaked its type and
        threshold onto every prescribed course that followed it, quietly
        turning required courses into pool options."""
        nonlocal current_group_type, current_threshold, pool_open
        nonlocal pool_indent_scoped, pool_pending
        pool_open          = False
        pool_indent_scoped = False
        pool_pending       = False
        current_group_type = heading_group_type
        current_threshold  = heading_threshold

    def detect_group_type(text):
        """
        Classify a requirement group header into one of four types:
          required       - must complete every course listed
          choose_one     - take any one course from the list (either/or)
          choose_credits - pick courses until N credit hours are reached
          choose_courses - pick N courses from the list
        Also returns the numeric threshold (credits or course count) if present.
        """
        tl = text.lower()
        threshold = None

        # ── choose_credits: "choose N credits", "minimum N credits", "N credit hours" ──
        # "Select 3-4 credits from the following" is common — the range exists
        # because the listed courses differ in size. Take the LOW end: any one
        # of the listed courses is an acceptable answer, so the smallest of them
        # must be enough to satisfy the pool. Requiring the high end would tell
        # a student their 3-credit choice had not finished a 3-4 credit pool.
        m = re.search(
            r"(?:choose|select|complete|minimum|at least)\s+(\d+)(?:\s*[-–—]\s*\d+)?"
            r"(?:\s+(?:additional|more|or\s+more|elective|electives|total|further|upper-division))*\s*credits?",
            tl
        )
        if m:
            return "choose_credits", int(m.group(1))

        # ── choose_courses: "choose N of", "select N courses", "complete N of" ──
        m = re.search(
            r"(?:choose|select|complete|take)\s+(\d+)\s+(?:of|course|from)",
            tl
        )
        if m:
            return "choose_courses", int(m.group(1))

        # ── choose_one: "one of the following", "or", option lists ──
        if any(p in tl for p in [
            "one of the following", "choose one", "select one",
            "complete one", "one of these", "either", " or "
        ]):
            return "choose_one", None

        # ── Gen-Ed ──
        if any(p in tl for p in ["general education", "gen ed", "gened", "university requirement",
                                   "knowledge domain", "integrative", "exploration", "foundation"]):
            return "gen_ed", None

        # ── Supporting / Related ──
        if any(p in tl for p in ["supporting", "related area", "elective"]):
            return "choose_credits", None   # usually a credit pool

        # ── Default: all required ──
        return "required", None

    # Walk through elements in order
    for el in req_content.find_all(["h2", "h3", "h4", "h5", "table"], recursive=True):
        tag = el.name

        # ── Section headers ──
        if tag in ["h2", "h3", "h4", "h5"]:
            text = el.get_text(strip=True)
            if len(text) < 4 or len(text) > 150:
                continue
            skip_words = ["admission", "suggested plan", "footnote", "note:", "sample plan",
                          "academic advising", "contact", "overview", "about", "career"]
            if any(s in text.lower() for s in skip_words):
                continue
            current_group      = text
            current_group_type, current_threshold = detect_group_type(text)
            # A new section ends any open pool and becomes the fallback the
            # pool's members revert to once the pool closes.
            heading_group_type = current_group_type
            heading_threshold  = current_threshold
            current_pool_seq   = 0
            pool_open          = False
            pool_indent_scoped = False
            pool_pending       = False

        # ── Also check paragraph/span text immediately before tables for pool instructions ──
        # e.g. "Select 3-4 credits from the following:"
        elif tag == "table":
            # A new table is a new context. Pools were only ever closed by an
            # <h2>-<h5>, but CourseLeaf splits a section across several tables
            # (one per option) with no heading between them, so a pool opened in
            # one table stayed open into the next and swallowed its prescribed
            # courses: World Languages Education had WLED 300 — a Prescribed
            # Course — reported as a pool option.
            #
            # current_pool_seq deliberately keeps counting. Restarting it per
            # table would give two pools in the same section the same number,
            # which is exactly the collision this field exists to prevent.
            close_pool()

            # Check preceding sibling text for "choose N credits" language.
            # Only a prose sibling counts. When two courselist tables are
            # adjacent the previous sibling IS the first table, and its own
            # "Select 3 credits from the following:" row then re-opened a pool
            # over the second table's prescribed courses — undoing the reset
            # immediately above.
            prev = el.find_previous_sibling()
            if prev is not None and getattr(prev, "name", None) == "table":
                prev = None
            if prev:
                prev_text = prev.get_text(" ", strip=True).lower()
                pg_type, pg_threshold = detect_group_type(prev_text)
                if pg_type in ("choose_credits", "choose_courses", "choose_one"):
                    current_group_type = pg_type
                    if pg_threshold:
                        current_threshold = pg_threshold
                    # The instruction sits OUTSIDE the table, so this pool's
                    # members are the table's ordinary rows and carry no
                    # blockindent. Open it, but don't let an unindented row
                    # close it — only the next heading or in-table pool row can.
                    if pg_type in ("choose_credits", "choose_courses"):
                        current_pool_seq  += 1
                        pool_open          = True
                        pool_indent_scoped = False
                        pool_pending       = False

            # Track the last non-"or" row so we can group "or" alternatives with it
            last_course_idx = None   # index of last appended row
            current_pair_id = None   # pair_group_id shared by an OR-alternative set

            for tr in el.find_all("tr"):
                tds = tr.find_all(["td", "th"])
                if not tds:
                    continue

                # An areaheader row ("Prescribed Courses", "Additional Courses",
                # "Requirements for the Option") starts a new sub-section inside
                # the table. It is a <tr>, not a heading tag, so it never reset
                # anything and a pool ran straight through it.
                if any("areaheader" in c for c in (tr.get("class") or [])):
                    close_pool()
                    continue

                cell_texts = [td.get_text(" ", strip=True) for td in tds]
                full_row   = " | ".join(cell_texts)
                first_cell = cell_texts[0].strip().lower()

                # CourseLeaf wraps a pool OPTION's code in <div class="blockindent">
                # and leaves prescribed courses unwrapped. That is the only
                # reliable "is this row part of the pool above it?" signal on the
                # page — the text alone cannot tell "Select 3 credits: CMPSC 121,
                # CMPSC 131, IST 140" apart from the required course that follows.
                is_indented = any(td.find("div", class_="blockindent") for td in tds)

                # ── Detect "or" rows: first cell is literally "or" or starts with "or " ──
                is_or_row = (
                    first_cell == "or"
                    or first_cell.startswith("or ")
                    or re.match(r"^or\s+[A-Z]{2,6}", cell_texts[0].strip())
                )

                # Must contain a course code somewhere in the row.
                #
                # CourseLeaf writes "both of these" as ONE <td class="codecol">
                # holding several <a> links joined by "&":
                #     BIOL 114 & BIOL 115 | Biology: ... - Lecture and ... - Lab
                # Keeping only the first match dropped every later code, so the lab
                # or second half of a sequence vanished from the program entirely.
                # Collect them all from the CODE CELL (cell 0 carries the codes in
                # both of the layouts handled below) and emit one row each, tied
                # together by a shared pair_branch_id so the audit reads them as ONE
                # branch rather than as interchangeable alternatives.
                combo_codes = [m.group(1) + " " + m.group(2) for m in
                               _CODE_IN_CELL.finditer(cell_texts[0])]
                # "&" is the AND marker. "or" rows are a different construct and are
                # already handled by the pair_group_id chain further down.
                is_combo = len(combo_codes) > 1 and "&" in cell_texts[0]
                
                code_match = _CODE_IN_CELL.search(full_row)
                if not code_match:
                    # Check for "select N credits" type rows inside the table
                    # Range thresholds ("Select 3-4 credits from the following:")
                    # were not matched at all, so the row did not register as a
                    # pool header — the courses under it silently joined the
                    # PREVIOUS pool. See detect_group_type for why the low end.
                    # Filler words sit between the number and "credits" more
                    # often than you would guess. Spanish B.A. heads two of its
                    # pools "Select 9 ADDITIONAL credits from the following",
                    # which matched nothing — so those 34 courses fell through to
                    # the section default and every one of them was stored as
                    # individually REQUIRED.
                    pool_match = re.search(
                        r"(?:select|choose|minimum)\s+(\d+)(?:\s*[-–—]\s*\d+)?"
                        r"(?:\s+(?:additional|more|or\s+more|elective|electives|total|further|upper-division))*\s*credits?",
                        full_row, re.I
                    )
                    # Not every pool header says "credits". Aerospace Engineering
                    # writes "Select one of the following sequences:" with the
                    # credit count in the hours column, and Anthropology writes
                    # "Select 2 of the following". Neither matched, so the courses
                    # under them joined the PREVIOUS pool — the same merge, by a
                    # different route.
                    #
                    # Where such a row carries a credit figure, prefer it and model
                    # the pool by credits: a "sequence" option is usually an "&"
                    # combo (AERSP 401A & AERSP 401B), and only a credit threshold
                    # stops half a sequence from satisfying the whole thing. Fall
                    # back to counting courses when the row has no credits.
                    if not pool_match:
                        word_match = re.search(
                            r"(?:select|choose|complete|take)\s+"
                            r"(one|two|three|four|five|six|\d+)\s+of\s+the\s+following",
                            full_row, re.I
                        )
                        if word_match:
                            words = {"one": 1, "two": 2, "three": 3,
                                     "four": 4, "five": 5, "six": 6}
                            token = word_match.group(1).lower()
                            count = words.get(token) or int(token)
                            hours = next(
                                (float(m.group(1)) for ct in reversed(cell_texts)
                                 for m in [re.match(r"^\s*(\d+(?:\.\d+)?)", ct.strip())]
                                 if m and ct.strip() and re.match(r"^[\d.\s–—-]+$", ct.strip())),
                                None,
                            )
                            if hours:
                                current_group_type = "choose_credits"
                                current_threshold  = int(hours)
                            else:
                                current_group_type = "choose_courses"
                                current_threshold  = count
                            current_pool_seq  += 1
                            pool_open          = True
                            pool_indent_scoped = True
                            pool_pending       = True
                    if pool_match:
                        # Each such row starts a NEW pool — this is the line the
                        # old code missed, which is why consecutive pools merged.
                        current_group_type = "choose_credits"
                        current_threshold  = int(pool_match.group(1))
                        current_pool_seq  += 1
                        pool_open          = True
                        pool_indent_scoped = True
                        pool_pending       = True
                    if not is_or_row:
                        current_pair_id = None   # break any open pair chain
                    continue

                course_code = f"{code_match.group(1)} {code_match.group(2)}"

                # Indentation is the page's own answer to "is this row part of
                # the list above it?", and it settles two different questions.
                #
                # 1. Does that "Select N credits" row introduce a list at all?
                #    Plenty of them do not. Aerospace Engineering's "Additional
                #    Courses" opens with "Select 1 credit of First-Year Seminar",
                #    a standalone instruction with no courses under it, and is
                #    followed by the ordinary requirement "AERSP 413 or AERSP
                #    450". Treating the comment as a pool header swallowed both
                #    into a 1-credit First-Year Seminar pool. So a comment row
                #    only opens a PENDING pool; the pool is real only once an
                #    indented row actually arrives. An unindented first row
                #    discards it, and the row is handled as it would have been
                #    with no comment there at all.
                #
                # 2. Where does a confirmed pool end? At the first unindented
                #    course row. "or" rows continue whatever they follow, so they
                #    never end one.
                if pool_open and pool_indent_scoped:
                    if is_indented:
                        pool_pending = False
                    elif pool_pending:
                        current_pool_seq -= 1     # keep seqs contiguous
                        close_pool()
                    elif not is_or_row:
                        close_pool()

                # Course title: first cell after the code cell that is not a
                # credits value. Rows come in two layouts — [code, title, credits]
                # and [code+title combined, credits]; blindly taking cell 1 wrote
                # the credits cell ("3", "1-0") as the title in the second layout.
                def _clean_title(text: str) -> str:
                    t = _CODE_IN_CELL_WIDE.sub("", text).strip(" –—/-or")
                    return re.sub(r"\s{2,}", " ", t).strip()

                _credit_cell = re.compile(r"^\d+(?:\.\d+)?(?:\s*[–—-]\s*\d+(?:\.\d+)?)?$")

                title = ""
                for ct in cell_texts[1:]:
                    if _credit_cell.match(ct.strip()):
                        continue
                    title = _clean_title(ct)
                    if title:
                        break
                if not title or _credit_cell.match(title):
                    title = _clean_title(cell_texts[0])
                    title = re.sub(r"^\s*or\s*", "", title, flags=re.I).strip()

                # Credits
                credits = ""
                for ct in reversed(cell_texts[-2:]):
                    cm = re.search(r"^\s*(\d(?:\.\d+)?)\s*$", ct)
                    if cm:
                        val = float(cm.group(1))
                        if 0.5 <= val <= 9:
                            credits = cm.group(1)
                            break
                if not credits:
                    for ct in cell_texts:
                        cm = re.search(r"\b(\d(?:\.\d+)?)\s*cr", ct, re.I)
                        if cm:
                            credits = cm.group(1)
                            break

                # Min grade
                min_grade = ""
                row_lower = full_row.lower()
                if "grade of c" in row_lower or "c or better" in row_lower or "minimum c" in row_lower:
                    min_grade = "C"
                elif "grade of b" in row_lower or "b or better" in row_lower:
                    min_grade = "B"

                # ── pair_group_id: link OR-alternative courses together ──
                # Each "A / or B / or C" chain gets a single shared integer ID so
                # the audit engine knows exactly which courses are interchangeable.
                row_group_type = current_group_type
                this_pair_id   = None

                if is_or_row and pool_open and current_group_type in (
                        "choose_credits", "choose_courses"):
                    # An "or" chain INSIDE a credit pool is a set of options, not
                    # a standalone choice. Lifting it out to choose_one told the
                    # student they MUST take one of them: Administration of
                    # Justice's "Select 3-4 credits" list of ten became BA 243
                    # required outright (a lone choose_one row evaluates as
                    # individually required), plus one of PHIL 106 / PHIL-STS 107,
                    # plus one of STS 101 / STS-PHIL 107 — three mandatory courses
                    # where the bulletin asks for one.
                    #
                    # Same reasoning as an "&" combo inside a pool: leave the rows
                    # in the pool and let the credit threshold do the enforcing.
                    # The "or" relationship carries no extra meaning here — these
                    # are usually cross-listings ("PHIL/STS 107") that the
                    # equivalence machinery already reconciles.
                    current_pair_id = None
                elif is_or_row:
                    row_group_type = "choose_one"
                    if last_course_idx is not None:
                        rows[last_course_idx]["group_type"] = "choose_one"
                        if rows[last_course_idx]["pair_group_id"] is None:
                            # Start a brand-new pair: assign a fresh ID to both rows
                            current_pair_id = _next_pair_id()
                            rows[last_course_idx]["pair_group_id"] = current_pair_id
                        # else: extending an existing chain (A or B or C) — reuse the ID
                    this_pair_id = current_pair_id
                else:
                    # Non-OR row breaks any open pair chain
                    current_pair_id = None
                    this_pair_id    = None

                base_row = {
                    "program_name":      full_title,
                    "college":           program["college"].replace("-", " ").title(),
                    "degree":            degree,
                    "campus":            campus,
                    "requirement_group": current_group,
                    "group_type":        row_group_type,
                    "group_threshold":   current_threshold,
                    "course_code":       course_code,
                    "course_title":      title[:120],
                    "credits":           credits,
                    "min_grade":         min_grade,
                    "pair_group_id":     this_pair_id,
                    "pool_seq":          (current_pool_seq
                                          if pool_open and row_group_type in
                                             ("choose_credits", "choose_courses")
                                          else None),
                    "url":               program["url"]
                }

                if is_combo:
                    # "BIOL 114 & BIOL 115" is ONE requirement made of two courses,
                    # not a choice between them. Emit a row per course, each with
                    # its own authoritative title and credits from the bulletin —
                    # the combo cell carries neither (every collapsed row in prod
                    # has credits=None), and splitting the concatenated title on
                    # " and " is unreliable because "Biology: Basic Concepts and
                    # Biodiversity" contains one.
                    #
                    # How the members are tied together depends on where the combo
                    # SITS, which is the part that is easy to get wrong:
                    #
                    #   * inside an "or" chain — "ACCTG 211 or (ACCTG 201 and
                    #     ACCTG 202)" — the combo is one BRANCH of a choice. It
                    #     needs the pair_group_id + pair_branch_id machinery so
                    #     half a branch satisfies nothing.
                    #
                    #   * anywhere else — nearly always a "Select 4-5 credits from
                    #     the following" pool — the combo is one OPTION among
                    #     several. Forcing it to choose_one here was wrong twice
                    #     over: it labelled a lecture+lab as "BIOL 114 or BIOL 115",
                    #     and it gave each sibling option its own pair_group_id, so
                    #     a student who took BIOL 114+115 was then told to take
                    #     BIOL 116 as well. Leave such rows in their pool and let
                    #     the credit threshold do the enforcing: BIOL 114 alone is
                    #     3 credits against a 4-5 credit pool, so it cannot satisfy
                    #     it without the lab.
                    in_or_chain = is_or_row and this_pair_id is not None
                    branch_id   = "b%d" % (this_pair_id if in_or_chain else _next_pair_id())
                    for member in combo_codes:
                        member_row = dict(base_row)
                        member_row["course_code"]    = member
                        member_row["pair_branch_id"] = branch_id
                        info = BULLETIN.get(member) or {}
                        if info.get("title"):
                            member_row["course_title"] = info["title"][:120]
                        if info.get("credits") is not None:
                            member_row["credits"] = info["credits"]
                        if in_or_chain:
                            member_row["group_type"]    = "choose_one"
                            member_row["pair_group_id"] = this_pair_id
                        else:
                            # Stay in the surrounding group; no pair id, so the
                            # members are pool options rather than alternatives
                            # to each other.
                            member_row["pair_group_id"] = None
                        rows.append(member_row)
                    # A combo is never the anchor of a later "or" chain — the chain
                    # would attach to only its last member.
                    last_course_idx = None
                    continue

                rows.append(base_row)
                last_course_idx = len(rows) - 1

    meta = {
        "program_name": full_title,
        "college":      program["college"].replace("-", " ").title(),
        "degree":       degree,
        "campus":       campus,
        "url":          program["url"],
        "courses_found": len(rows)
    }

    return rows, meta


# ── STEP 3: Write styled Excel ───────────────────────────────────────────────

def write_excel(df, df_summary, path):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="All Requirements", index=False)
        df_summary.to_excel(writer, sheet_name="Programs Index", index=False)

        # One sheet per college (UP programs only to keep it manageable)
        df_up = df[df["campus"] == "University Park"]
        for college in sorted(df_up["college"].unique()):
            safe = re.sub(r"[^\w ]", "", college).strip()[:28]
            if safe:
                df_up[df_up["college"] == college].to_excel(
                    writer, sheet_name=safe, index=False
                )

    wb = openpyxl.load_workbook(path)

    hdr_fill  = PatternFill("solid", fgColor="1A3A6B")
    hdr_font  = Font(bold=True, color="FFFFFF", size=10, name="Segoe UI")
    alt_fill  = PatternFill("solid", fgColor="EFF6FF")
    cell_font = Font(size=10, name="Segoe UI")
    wrap      = Alignment(wrap_text=True, vertical="top")
    center    = Alignment(horizontal="center", vertical="center")
    thin_bot  = Border(bottom=Side(style="thin", color="DBEAFE"))

    col_w = {
        "program_name":      40,
        "college":           22,
        "degree":             8,
        "campus":            16,
        "requirement_group": 30,
        "group_type":        14,
        "group_threshold":   14,
        "course_code":       13,
        "course_title":      46,
        "credits":            8,
        "min_grade":          9,
        "pair_group_id":     13,
        "url":                0,
        "name":              44,
        "courses_found":     15,
    }

    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        # Header row
        for cell in ws[1]:
            cell.font      = hdr_font
            cell.fill      = hdr_fill
            cell.alignment = center
            ws.row_dimensions[1].height = 22

        # Column widths
        for ci, col_cells in enumerate(ws.iter_cols(min_row=1, max_row=1), 1):
            key = str(col_cells[0].value or "").lower().replace(" ", "_")
            w   = col_w.get(key, 18)
            col_ltr = get_column_letter(ci)
            if w == 0:
                ws.column_dimensions[col_ltr].hidden = True
            else:
                ws.column_dimensions[col_ltr].width = w

        # Data rows
        for ri, row in enumerate(ws.iter_rows(min_row=2), 2):
            for cell in row:
                cell.font      = cell_font
                cell.alignment = wrap
                cell.border    = thin_bot
                if ri % 2 == 0:
                    cell.fill = alt_fill

    wb.save(path)


# ── STEP 4: Write TXT ────────────────────────────────────────────────────────

def write_txt(df, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("PENN STATE UNIVERSITY — UNDERGRADUATE MAJOR REQUIREMENTS\n")
        f.write("Source: bulletins.psu.edu\n")
        f.write("=" * 72 + "\n\n")

        current_prog  = None
        current_group = None

        sort_cols = ["campus", "college", "program_name", "requirement_group", "course_code"]
        for col in sort_cols:
            if col not in df.columns:
                sort_cols.remove(col)

        for _, row in df.sort_values(sort_cols).iterrows():
            prog_key = f"{row['program_name']} | {row['campus']}"

            if prog_key != current_prog:
                current_prog  = prog_key
                current_group = None
                f.write("\n" + "=" * 72 + "\n")
                f.write(f"  PROGRAM : {row['program_name']}\n")
                f.write(f"  DEGREE  : {row['degree']}\n")
                f.write(f"  COLLEGE : {row['college']}\n")
                f.write(f"  CAMPUS  : {row['campus']}\n")
                f.write("=" * 72 + "\n")

            if row["requirement_group"] != current_group:
                current_group = row["requirement_group"]
                f.write(f"\n  >> [{row['group_type']}]  {row['requirement_group']}\n")
                f.write(f"    {'─' * 55}\n")

            grade  = f"  <- min grade: {row['min_grade']}" if row["min_grade"] else ""
            cr     = f"{row['credits']} cr" if row["credits"] else "?"
            pair   = f"  [pair:{row['pair_group_id']}]" if row.get("pair_group_id") else ""
            f.write(f"    {row['course_code']:<14}  {cr:<6}  {row['course_title']}{pair}{grade}\n")

        f.write("\n\n" + "=" * 72 + "\n")
        total_progs = df["program_name"].nunique()
        total_rows  = len(df)
        f.write(f"  Total programs scraped : {total_progs}\n")
        f.write(f"  Total requirement rows : {total_rows}\n")
        f.write("=" * 72 + "\n")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Scrape PSU bulletin → PSU_Major_Requirements.xlsx")
    parser.add_argument(
        "--program",
        action="append",
        default=[],
        help="Only scrape programs whose name contains this substring (repeatable). "
             "Example: --program 'Enterprise Technology'",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=0,
        help="Stop after N University Park programs (0 = no limit)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching programs and exit without scraping requirements",
    )
    args = parser.parse_args(argv)

    # Repo root (two levels up from backend/scripts/) — load_catalog.py reads the
    # Excel output from there
    output_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

    print("=" * 60)
    print("Penn State Major Requirements Scraper")
    print("=" * 60)

    programs = get_all_programs()
    if not programs:
        print("No programs found.")
        return

    if args.program:
        needles = [n.lower() for n in args.program]
        programs = [
            p for p in programs
            if any(n in p["name"].lower() for n in needles)
        ]
        print(f"  Filtered to {len(programs)} programs matching {args.program!r}")

    if args.dry_run:
        for p in programs:
            print(f"  - {p['name']}  ({p['college']})")
        print(f"Total: {len(programs)}")
        return

    all_rows    = []
    all_summary = []

    skipped = 0
    up_scraped = 0
    for i, prog in enumerate(programs, 1):
        print(f"[{i:>3}/{len(programs)}] {prog['name'][:65]}", end="", flush=True)
        rows, meta = scrape_program_requirements(prog)

        # Skip non-University Park programs
        if meta.get("campus", "University Park") != "University Park":
            print(f"  SKIP ({meta['campus']})")
            skipped += 1
            time.sleep(0.2)
            continue

        all_rows.extend(rows)
        all_summary.append(meta)
        up_scraped += 1
        print(f"  OK {len(rows)} courses")
        time.sleep(0.35)

        if args.max and up_scraped >= args.max:
            print(f"\nReached --max {args.max} University Park programs")
            break

    print(f"\nSkipped {skipped} non-University Park programs")

    print(f"\nTotal requirement rows collected: {len(all_rows)}")

    if not all_rows:
        print("No data collected.")
        return

    df         = pd.DataFrame(all_rows)
    df_summary = pd.DataFrame(all_summary)

    excel_path = os.path.join(output_dir, "PSU_Major_Requirements.xlsx")
    txt_path   = os.path.join(output_dir, "PSU_Major_Requirements.txt")

    print(f"\nWriting Excel: {excel_path}")
    write_excel(df, df_summary, excel_path)

    print(f"Writing TXT:   {txt_path}")
    write_txt(df, txt_path)

    print("\n" + "=" * 60)
    print("COMPLETE")
    print(f"  Programs : {df['program_name'].nunique()}")
    print(f"  Rows     : {len(df)}")
    print(f"  Excel    : PSU_Major_Requirements.xlsx")
    print(f"  TXT      : PSU_Major_Requirements.txt")
    print("=" * 60)


if __name__ == "__main__":
    main()
