"""
Parser for a PSU bulletin "Entrance to Major" section.

Entrance to Major is a GATE, not a pile of extra credits. Every course PSU names
there is already a requirement of the major — verified across the sample: all of
Astronomy's six, all nine of ETI's, all six of the AI program's. So this must
never become requirement rows; it would double-count the credits and schedule
the same course twice. What it adds is a *deadline* ("by the end of the fourth
semester"), a *minimum grade* (usually C), and a *GPA floor*.

Shapes the bulletin actually uses, all seen in the wild:

  1. GPA only          "attain at least a C (2.00) cumulative grade-point average
                        ... and have at least third-semester classification"
  2. Flat course list  "Completed and earned a grade of C or better in each of the
                        following courses: ASTRO 291, CHEM 110, MATH 140, ..."
  3. AND of OR-groups  "(ETI 100 or HCDD 113 or CYBER 100 or IST 110 or A-I 100),
                        and (IST 140 or CMPSC 121 or CMPSC 131), and IST 210, ..."
  4. Narrative         enrollment-control prose, cohort-by-cohort
  5. Non-course        "80 hours of volunteer or paid education work experience",
                        clearances, portfolio reviews

Only 1-3 are modelled. Anything in 4-5 is kept verbatim in `notes` and sets
`has_unmodelled`, because telling a student they have cleared a gate they have
not is the failure that matters here — the same reasoning as
`unstructured_credits` on credentials.
"""

import html
import re
import unicodedata

# The course links carry the code in the query string — "?P=ETI%20100" — which
# is the one place on the page it appears without NBSPs or markup in the middle.
_LINK_RE = re.compile(r'<a[^>]+\?P=([A-Za-z0-9%\-]+?%20\d{1,3}[A-Za-z]?)["\'][^>]*>.*?</a>',
                      re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")

_GPA_RE = re.compile(
    # "a minimum cumulative grade point average of 2.00"
    r"(?:minimum\s+)?(?:cumulative\s+)?grade[\s-]point average"
    r"(?:\s*\(C?GPA\))?(?:\s+of)?\s*(?:at least\s*)?(\d\.\d{1,2})"
    # "at least a 2.00 cumulative grade-point average"
    r"|(?:at least|minimum of|minimum)\s+a?\s*(\d\.\d{1,2})\s*(?:cumulative\s+)?"
    r"(?:grade[\s-]point average|gpa)"
    # "attain at least a C (2.00) cumulative grade-point average" — the most
    # common phrasing of all, and the parenthesised number is the only number
    # in it, so neither branch above sees it.
    r"|\((\d\.\d{1,2})\)\s*cumulative\s+grade[\s-]point average",
    re.I,
)
_MIN_GRADE_RE = re.compile(r"grade of ([A-D][+-]?) or better", re.I)
_SEMESTER_RE = re.compile(
    r"(third|fourth|fifth|sixth|second)[\s-]semester (?:classification|standing)", re.I
)
_WORD_TO_NUM = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}

# Phrases that mean "there is a condition here we cannot check".
#
# Matched on word boundaries and kept specific. A bare "application" flagged the
# Artificial Intelligence Methods and *Applications* major off its own name, and
# a gate wrongly marked unverifiable is a gate the student is told to go ask an
# adviser about for no reason.
_UNMODELLED = (
    r"volunteer", r"work experience", r"clearance(?:s)?", r"background check",
    r"portfolio", r"audition", r"interview", r"essay",
    r"application (?:process|materials|form|deadline|instructions)",
    r"apply to the major", r"admission restrictions",
    r"enrollment control(?:s)?", r"administrative enrollment",
    r"space availability", r"competitive", r"letter(?:s)? of recommendation",
    r"observation hours", r"field experience hours",
)
_UNMODELLED_RE = re.compile(r"\b(?:" + "|".join(_UNMODELLED) + r")\b", re.I)


def _norm_code(raw: str) -> str:
    """'ETI%20100' -> 'ETI 100'."""
    code = html.unescape(raw).replace("%20", " ").replace("+", " ")
    code = unicodedata.normalize("NFKD", code).replace("\xa0", " ")
    return re.sub(r"\s+", " ", code).strip().upper()


def _to_text(fragment: str) -> str:
    """Strip markup, replacing each course link with a «CODE» token so the
    grouping logic can see structure without tripping over nested spans."""
    def sub(m):
        return f"«{_norm_code(m.group(1))}»"

    text = _LINK_RE.sub(sub, fragment)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKD", text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _codes(text: str) -> list[str]:
    return re.findall(r"«([^»]+)»", text)


_ANNOTATION_RE = re.compile(r"\([^()«»]*\)")


def _strip_annotations(text: str) -> str:
    """Drop parentheticals that contain no course code.

    PSU annotates options inline — "HCDD 113S (FYS) or CYBER 100S (FYS)" — and
    those bare parentheses split the surrounding group. ETI's single 7-way
    alternative came out as three separate groups, which reads as "you need one
    from each of three lists": a gate three times harder than the real one."""
    prev = None
    while prev != text:
        prev = text
        text = _ANNOTATION_RE.sub(" ", text)
    return text


def parse_requirement(text: str) -> list[list[list[str]]]:
    """Split a requirement sentence into AND-ed groups of OR-ed branches, where a
    branch is one or more courses that must ALL be taken.

        "(A or B), and (C or D), and E"   -> [[[A],[B]], [[C],[D]], [[E]]]
        "A or B or (C and D)"             -> [[[A],[B],[C,D]]]

    The second shape is why branches exist. Accounting's gate is
    "ACCTG 211 or ACCTG 211H or (ACCTG 201 and ACCTG 202)"; reading that inner
    pair as alternatives would clear the gate for a student holding only
    ACCTG 201, which is the direction that actually hurts. Same rule the audit
    engine uses for compound choose-one branches.

    Parentheses carry the disambiguation, and PSU is consistent about it: a
    parenthesised run joined by "or" is a group of alternatives, one joined by
    "and" is a single branch inside the surrounding alternation. Outside
    parentheses, "and" and commas separate groups.
    """
    text = _strip_annotations(text)

    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    joined_by_or = False

    def flush():
        nonlocal current
        if current:
            groups.append(current)
            current = []

    for kind, payload, separator in _tokenise(text):
        if kind == "paren_and":
            # One branch of several courses, belonging to the surrounding chain.
            if not joined_by_or:
                flush()
            current.append(payload)
        elif kind == "paren_or":
            flush()
            current = [[c] for c in payload]
        else:                                    # a bare code
            if joined_by_or and current:
                current.append(payload)
            else:
                flush()
                current = [payload]
        joined_by_or = separator == "or"
    flush()
    return [g for g in groups if g]


def _tokenise(text: str):
    """Yield (kind, payload, separator_after) for each course-bearing item.

    kind is "code" (payload = [code]), "paren_or" (payload = [code, ...]) or
    "paren_and" (payload = [code, ...]). separator_after is "or" when the text
    between this item and the next contains a bare "or", else "and"."""
    items: list[tuple[str, list[str], int, int]] = []
    consumed: list[tuple[int, int]] = []

    for m in re.finditer(r"\(([^()]*)\)", text):
        inner = m.group(1)
        codes = _codes(inner)
        if not codes:
            continue
        kind = "paren_and" if (not re.search(r"\bor\b", inner, re.I)
                               and re.search(r"\band\b", inner, re.I)
                               and len(codes) > 1) else "paren_or"
        items.append((kind, codes, m.start(), m.end()))
        consumed.append((m.start(), m.end()))

    for m in re.finditer(r"«([^»]+)»", text):
        if any(a <= m.start() < b for a, b in consumed):
            continue
        items.append(("code", [m.group(1)], m.start(), m.end()))

    items.sort(key=lambda it: it[2])
    for i, (kind, payload, _start, end) in enumerate(items):
        nxt = items[i + 1][2] if i + 1 < len(items) else len(text)
        between = text[end:nxt]
        separator = "or" if re.search(r"\bor\b", between, re.I) else "and"
        yield kind, payload, separator


def parse_entrance_section(fragment: str) -> dict:
    """Parse the HTML between <h2>Entrance to Major</h2> and the next <h2>."""
    items = re.findall(r"<li[^>]*>(.*?)</li>", fragment, re.S | re.I)
    if not items:
        items = re.findall(r"<p[^>]*>(.*?)</p>", fragment, re.S | re.I)

    whole = _to_text(fragment)
    spec: dict = {
        "gpa_min": None,
        "min_grade": None,
        "semester_standing": None,
        "groups": [],
        "notes": [],
        "has_unmodelled": False,
        "raw_text": whole[:4000],
    }

    # A page can state several GPA figures that mean different things. Accounting
    # names 3.10 for entrance and 2.60-3.09 for "considered on a space
    # availability basis"; picking whichever matched first told the student the
    # bar was 2.60. When the figures disagree, assert none of them and say so —
    # a number the student plans around has to be the right one.
    found = sorted({float(g) for g in
                    (grp for mm in _GPA_RE.finditer(whole) for grp in mm.groups())
                    if g})
    spec["gpa_candidates"] = found
    if len(found) == 1:
        spec["gpa_min"] = found[0]
    elif len(found) > 1:
        spec["has_unmodelled"] = True
        spec["notes"].append(
            "Several GPA thresholds are stated (" +
            ", ".join(f"{g:.2f}" for g in found) +
            "); check which applies with an adviser."
        )
    m = _MIN_GRADE_RE.search(whole)
    if m:
        spec["min_grade"] = m.group(1).upper()
    m = _SEMESTER_RE.search(whole)
    if m:
        spec["semester_standing"] = _WORD_TO_NUM.get(m.group(1).lower())

    seen: set[tuple] = set()
    for raw_item in items:
        text = _to_text(raw_item)
        if not text:
            continue
        for group in parse_requirement(text):
            key = tuple(tuple(b) for b in group)
            if key not in seen:
                seen.add(key)
                spec["groups"].append(group)
        if not _codes(text) and _UNMODELLED_RE.search(text):
            spec["notes"].append(text[:400])
            spec["has_unmodelled"] = True

    # Enrollment-control prose can name courses AND still be unmodellable — it
    # is cohort-by-cohort and space-limited. Scan the whole section, not just
    # the items that happened to carry no course code.
    if _UNMODELLED_RE.search(whole):
        spec["has_unmodelled"] = True
        if not spec["notes"]:
            spec["notes"].append(whole[:400])

    return spec


# CourseLeaf puts the whole "how to get in" tab in one container, always with
# this id. The HEADING inside it is not stable: "Entrance to Major" on ETI and
# Astronomy, "Direct Admission to the Major" on Nursing and Law and Society,
# "Entrance Procedures" on Architecture. Keying on the heading text found the
# gate for 186 of the 225 selectable majors and silently reported "no section"
# for the other 39 — including every Nursing and Architecture program.
_TAB_RE = re.compile(
    r'<div[^>]*id="howtogetintextcontainer"[^>]*>(.*?)</div>\s*(?=<div[^>]*(?:id="\w+textcontainer"|class="[^"]*tab_content))',
    re.I | re.S,
)
_TAB_OPEN_RE = re.compile(r'<div[^>]*id="howtogetintextcontainer"[^>]*>', re.I)


def extract_section(page_html: str) -> str | None:
    """The "how to get in" tab: entrance/admission requirements, whatever the
    page happens to call them."""
    m = _TAB_RE.search(page_html)
    if m:
        return m.group(1)
    # Fall back to a bounded slice from the container onwards — some pages close
    # the tab differently and a greedy match would swallow the whole document.
    m = _TAB_OPEN_RE.search(page_html)
    if m:
        rest = page_html[m.end():]
        nxt = re.search(r'<div[^>]*id="\w+textcontainer"', rest)
        return rest[:nxt.start()] if nxt else rest[:20000]
    # Last resort: the old heading match, for a page with no tab structure.
    m = re.search(r"<h2[^>]*>\s*Entrance to Major\s*</h2>", page_html, re.I)
    if not m:
        return None
    rest = page_html[m.end():]
    nxt = re.search(r"<h2[^>]*>", rest)
    return rest[:nxt.start()] if nxt else rest[:20000]
