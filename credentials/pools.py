"""
Pool-sentence parsing — the "Select N credits …" rows in a CourseLeaf course list.

A PSU credential page expresses most of its requirement in prose rows that carry no
course code, e.g.

    Select 11 credits (at least 6 credits at the 400 level) in PSYCH
    Select 3 credits from any ANTH course except ANTH 1
    Select 6 credits from the ANTH 400-489 range
    Select 2-7 credits from the following:
    Select 6 credits from Engineering Cluster:
    Select one of the following:

`scrape_psu.py` drops every one of these (its `code_match` guard at scrape_psu.py:243
requires a course code in the row), which is how "Psychology, Minor" ended up as 7 of its
real 18 credits.  This module turns them into a structured `PoolSpec`.

The critical distinction is **enumerable vs. departmental**:

  enumerable  — the pool's options are the course rows that follow it in the table
                ("… from the following:", "… from Engineering Cluster:").  Becomes a
                `choose_credits` / `choose_courses` group, which the audit engine
                already understands.

  departmental — the pool is defined by a rule over the whole catalog, not a list
                ("… in PSYCH", "… from the ANTH 400-489 range").  There is no course
                list to enumerate, so it becomes a `dept_credits` group (see
                dept_credits.py).

CourseLeaf is consistent about this: an enumerable pool sentence ends with a colon,
because a list follows it.  That is the primary signal; a recognised departmental
pattern overrides it only when no colon is present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict


# A PSU course code: 2-6 letters, then a number that may carry a suffix (ANTH 45N).
_DEPT   = r"[A-Z]{2,6}"
_NUM    = r"\d{1,3}[A-Z]?"
_CODE   = rf"{_DEPT}\s?{_NUM}"

# "11 credits", "2-7 credits", "one credit"
_AMOUNT = r"(\d+)\s*(?:[-–—]\s*(\d+))?"

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass
class PoolSpec:
    """One parsed "Select N …" row."""

    # What is being counted.
    unit: str = "credits"          # "credits" | "courses"
    threshold: int = 0             # low end of the range — the satisfiable minimum
    threshold_max: int | None = None   # high end, when the page states a range ("2-7")

    # How the options are defined.
    enumerable: bool = True        # True -> options are the rows that follow
    dept: str | None = None        # departmental pool: the subject prefix ("PSYCH")
    # Some pools span a list of subjects: "… at the 400 level from ACCTG, BA, … or STAT"
    depts: list[str] = field(default_factory=list)
    min_level: int | None = None   # "… from the ANTH 400-489 range" -> 400
    max_level: int | None = None   # -> 489
    # "… (at least 6 credits at the 400 level)" -> level 400, credits 6
    sub_level: int | None = None
    sub_credits: int | None = None
    exclude: list[str] = field(default_factory=list)   # "… except ANTH 1"

    text: str = ""                 # the original sentence, kept for the UI and for review

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], "")}


def is_section_label(text: str, section: str) -> bool:
    """Whether a code-less row is just restating its section heading.

    Some pages give a section's own name a credit total on a plain row ("Additional
    Courses … 3"), which is a heading, not a requirement.  Matching it against the
    open section is precise; guessing from length is not — "Environment or Climate
    Elective" is short and label-shaped but is a real 3-credit requirement, and
    treating it as a heading cost the One Health certificate 6 of its 13 credits.
    """
    t = re.sub(r"[^a-z ]", "", (text or "").strip().lower()).strip()
    s = re.sub(r"[^a-z ]", "", (section or "").strip().lower()).strip()
    return bool(t) and (t == s or t == "total credits")


def looks_like_pool(text: str, has_hours: bool = False) -> bool:
    """Whether a code-less table row is a requirement sentence rather than a note.

    `has_hours` is the decisive signal: in CourseLeaf a row with no course code but a
    numeric `td.hourscol` is *always* stating a requirement amount, whatever wording it
    uses ("Students must take 9 credits within one or more of the following areas:").
    The verb list alone missed those and silently dropped the requirement.
    """
    t = (text or "").strip().lower()
    if not t:
        return False
    starts_with_verb = bool(
        re.match(r"^(?:select|choose|complete|take|students must|a minimum of)\b", t)
    )
    if has_hours:
        # A credits column alone is not enough: some pages give a plain section label
        # its own credit total ("Additional Courses", "Environment or Climate
        # Elective"), which is a heading, not a requirement sentence.  A real
        # requirement.  Section headings are filtered out by name before we get here
        # (see is_section_label), so a row that carries its own credit amount is a
        # requirement — including ones with no verb and no number at all
        # ("Environment or Climate Elective", "Demonstrate language skills in a
        # currently spoken language other than English").
        return True
    return starts_with_verb


def parse_pool(text: str, hours_cell: str = "") -> PoolSpec | None:
    """Parse a "Select N credits …" sentence into a PoolSpec.

    `hours_cell` is the row's `td.hourscol` value, which CourseLeaf fills in with the
    same number the sentence states ("11", or "2-7" for a range).  It is the more
    reliable of the two, so it wins when both are present.

    Returns None when the row is not a requirement sentence at all.
    """
    raw = re.sub(r"\s+", " ", (text or "")).strip()
    has_hours = bool(re.match(r"^\s*\d+(?:\s*[-–—]\s*\d+)?\s*$", (hours_cell or "").strip()))
    if not looks_like_pool(raw, has_hours):
        return None

    spec = PoolSpec(text=raw)
    body = raw.rstrip()

    # ── Unit + amount ────────────────────────────────────────────────────────
    # Prefer the hours column; it is machine-written and unambiguous.
    lo = hi = None
    m = re.match(rf"^\s*{_AMOUNT}\s*$", (hours_cell or "").strip())
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else None

    if lo is None:
        m = re.search(rf"{_AMOUNT}\s*credits?\b", body, re.I)
        if m:
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else None

    if lo is not None:
        spec.unit = "credits"
        spec.threshold = lo
        spec.threshold_max = hi
    else:
        # "Select 2 courses from the following:" / "Select one of the following:"
        m = re.search(r"(?:select|choose|complete|take)\s+(\d+)\s+(?:courses?|of)", body, re.I)
        if m:
            spec.unit, spec.threshold = "courses", int(m.group(1))
        else:
            m = re.search(r"(?:select|choose|complete|take)\s+(\w+)\s+(?:courses?|of)", body, re.I)
            word = m.group(1).lower() if m else ""
            if word in _WORD_NUMBERS:
                spec.unit, spec.threshold = "courses", _WORD_NUMBERS[word]
            else:
                return None   # a sentence we cannot quantify — caller quarantines it

    # ── "(at least 6 credits at the 400 level)" sub-constraint ───────────────
    m = re.search(rf"at least\s+{_AMOUNT}\s*credits?\s+at the\s+(\d{{3}})\s*[-–—]?\s*level", body, re.I)
    if m:
        spec.sub_credits = int(m.group(1))
        spec.sub_level   = int(m.group(3))

    # ── Enumerable vs departmental ───────────────────────────────────────────
    # A trailing colon means "the rows below are the options" — CourseLeaf is
    # consistent about this, so it is the primary signal.
    spec.enumerable = body.endswith(":")

    if not spec.enumerable:
        _parse_departmental(spec, body)
        # A sentence with no colon AND no recognisable subject is not something we can
        # evaluate; say so plainly rather than guessing.
        if not (spec.dept or spec.depts):
            return None

    return spec


def _parse_departmental(spec: PoolSpec, body: str) -> None:
    """Fill in dept / level-range / exclusions for a non-enumerable pool."""

    # Exclusions first: several branches below return early, and an exclusion applies
    # whichever shape the sentence turns out to be.
    m = re.search(r"\b(?:except|excluding|other than)\b(.*)$", body, re.I)
    if m:
        spec.exclude = [
            re.sub(r"\s+", " ", c).strip()
            for c in re.findall(rf"\b{_DEPT}\s?{_NUM}\b", m.group(1))
        ]

    # "from the ANTH 400-489 range"  /  "in the ANTH 400-499 range"
    m = re.search(rf"\b({_DEPT})\s+(\d{{3}})\s*[-–—]\s*(\d{{3}})\s*range", body)
    if m:
        spec.dept, spec.min_level, spec.max_level = m.group(1), int(m.group(2)), int(m.group(3))
        return

    # "… from ACCTG, BA, BLAW, EBF, … or STAT" — a comma list of subjects.
    m = re.search(rf"\bfrom\s+((?:{_DEPT}\s*,\s*)+(?:or\s+)?{_DEPT})\s*\.?$", body)
    if m:
        spec.depts = re.findall(_DEPT, m.group(1).replace(" or ", " "))
        spec.depts = [d for d in spec.depts if d != "or"]
        return _level_only(spec, body)

    # "from ENGL 200 - ENGL 299" — an explicit course-number span.
    m = re.search(rf"\b({_DEPT})\s*(\d{{1,3}})\s*[-–—]\s*(?:{_DEPT})?\s*(\d{{1,3}})\b", body)
    if m and not re.search(r"credits?", m.group(0), re.I):
        spec.dept      = m.group(1)
        spec.min_level = int(m.group(2))
        spec.max_level = int(m.group(3))
        return None

    # "6 credits of 400-level ANSC courses" / "any 200-level CAS course"
    # / "1 to 400-level ARTH courses" / "additional 400-level CMPEN courses"
    m = re.search(rf"(\d{{3}})\s*[-–—]?\s*level\s+(?:\w+\s+)??({_DEPT})\b", body)
    if m:
        spec.dept      = m.group(2)
        spec.min_level = int(m.group(1))
        return None

    # "6 credits of additional ECON courses at the 400-level"
    m = re.search(rf"\b(?:of|from)\s+(?:\w+\s+)?({_DEPT})\s+courses?\b", body)
    if m:
        spec.dept = m.group(1)
        return _level_only(spec, body)

    # "at the 400 level in PSYCH" / "in PSYCH" / "from any ANTH course"
    m = (re.search(rf"\bin\s+(?:the\s+)?({_DEPT})\b(?!\s+\d)", body)
         or re.search(rf"\bfrom any\s+({_DEPT})\b", body)
         or re.search(rf"\bfrom\s+({_DEPT})\s+courses?\b", body))
    if m:
        spec.dept = m.group(1)

    # "at the 400 level" as the whole constraint (no explicit range)
    if (spec.dept or spec.depts) and spec.min_level is None:
        m = re.search(r"at the\s+(\d{3})\s*[-–—]?\s*level", body, re.I)
        # Only a *whole-pool* level constraint — a sub-constraint was captured above
        # as sub_level and must not be promoted to the pool's floor.
        if m and spec.sub_level is None:
            spec.min_level = int(m.group(1))


def _level_only(spec: PoolSpec, body: str) -> None:
    """Apply a whole-pool level constraint to a multi-subject pool."""
    m = re.search(r"at the\s+(\d{3})\s*[-–—]?\s*level", body, re.I)
    if m and spec.sub_level is None:
        spec.min_level = int(m.group(1))
    return None
