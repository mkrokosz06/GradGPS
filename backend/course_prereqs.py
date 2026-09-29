"""
Course prerequisites and corequisites, read from the PSU bulletin.

The timeline orders courses by where PSU's plan puts them (SAP path) or by course
level (Layer 1), and neither is enough on its own: re-packing a partly-complete
student's plan split ARCH 203 from its corequisites AE 421 / ARCH 231, and put
FIN 301 in the same term as the ACCTG 211 it needs. This module supplies the
facts that ordering has to respect.

Data: `scripts/bulletin_prereqs.json`, written by `scripts/scrape_bulletin_courses.py`
from each course block's "Enforced Prerequisite at Enrollment:" / "Concurrent at
Enrollment:" lines. Stored parsed, as

    {"FIN 301": {"pre": [["ENGL 15", "ENGL 30H", ...], ["ACCTG 211", ...]],
                 "co":  [...]}}

Each inner list is ONE clause — take any one of its courses — and every clause
must be met. `pre` clauses must be finished in an earlier term; `co` clauses may
be taken in the same term (or earlier).

The parse is deliberately conservative. A clause that can be met some other way
(placement exam, instructor permission, "or equivalent", semester standing) is
dropped, and "A or (B and C)" is flattened to "any of A, B, C". Both choices can
only make a constraint weaker, never invent one — being wrong here schedules a
course too early, which is where the timeline already was, never later than it
needs to be.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).parent / "scripts" / "bulletin_prereqs.json"

_CODE = re.compile(r"\b([A-Z]{2,6}(?:-[A-Z]{1,4})?)\s?(\d{1,3}[A-Z]?)\b")

# The headings PSU uses inside a course block. One <p> can glue several together
# ("... Enforced Concurrent at Enrollment: ARCH 231"), so text is split on them.
_HEADING = re.compile(
    r"((?:Enforced\s+|Recommended\s+)?"
    r"(?:Prerequisites?|Corequisites?|Concurrents?|Concurrent\s+Courses?|Preparation)"
    r"(?:\s+or\s+Concurrent)?(?:\s+at\s+Enrollment)?\s*:)",
    re.I,
)

# A clause mentioning any of these can be met without taking a listed course.
_ESCAPES = ("placement", "permission", "consent", "approval", "equivalent",
            "standing", "score", "exam", "instructor")

# "a grade of C or better in" — the "or" here is not an alternative.
_GRADE_PHRASE = re.compile(
    r"(?:a\s+)?(?:grade\s+of\s+)?\b[A-D][+-]?\s+or\s+(?:better|higher|above)", re.I)


def norm(code: str) -> str:
    """'MATH 140H' -> 'MATH 140', 'SPLED395W' -> 'SPLED 395'. Section letters stay
    (CAS 100A, ENGL 202C); the honors/writing/seminar suffixes are the same course."""
    code = re.sub(r"\s+", " ", (code or "").replace("\xa0", " ").strip().upper())
    m = _CODE.fullmatch(code)
    if m:
        code = f"{m.group(1)} {m.group(2)}"
    return re.sub(r"(\d)[HWMXYNS]$", r"\1", code)


def _split_top(body: str) -> list[str]:
    """Split on ';' and ' and ' outside parentheses."""
    parts, buf, depth, i = [], "", 0, 0
    while i < len(body):
        ch = body[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and ch == ";":
            parts.append(buf); buf = ""; i += 1; continue
        if depth == 0 and body[i:i + 5].lower() == " and ":
            parts.append(buf); buf = ""; i += 5; continue
        buf += ch
        i += 1
    parts.append(buf)
    return parts


def _clauses(body: str) -> list[tuple[list[str], bool]]:
    """-> [(alternatives, mentions_concurrent)]."""
    out = []
    for part in _split_top(body):
        text = _GRADE_PHRASE.sub(" ", part.replace("\xa0", " "))
        low = text.lower()
        if any(w in low for w in _ESCAPES):
            continue
        codes: list[str] = []
        for a, b in _CODE.findall(text):
            c = norm(f"{a} {b}")
            if c not in codes:
                codes.append(c)
        # Shorthand: "CMPSC 131 or 132".
        first = _CODE.search(text)
        if first:
            for n in re.findall(r"\bor\s+(\d{2,3}[A-Z]?)\b", text):
                c = norm(f"{first.group(1)} {n}")
                if c not in codes:
                    codes.append(c)
        if not codes:
            continue
        conc = "concurrent" in low
        if re.search(r"\bor\b", low):
            out.append((codes, conc))
        else:
            # "SPLED 395, SPLED 401, SPLED 425" with no "or" is a list of requirements.
            out.extend(([c], conc) for c in codes)
    return out


def parse(paragraphs: list[str]) -> dict[str, list[list[str]]]:
    """Bulletin requisite paragraphs -> {"pre": [...], "co": [...]}."""
    segs: list[tuple[str, str]] = []
    for p in paragraphs:
        head = ""
        for piece in _HEADING.split(p):
            if _HEADING.fullmatch(piece.strip() or "x"):
                head = piece
            elif head:
                segs.append((head, piece))

    # "MATH 230 or Concurrent: MATH 232" — a dangling "or" joins the next segment
    # into one disjunction, which the weaker (concurrent) reading covers.
    merged: list[tuple[str, str]] = []
    for head, body in segs:
        if merged and re.search(r"\bor\s*$", merged[-1][1], re.I):
            merged[-1] = ("Concurrent:", merged[-1][1] + " " + body)
        else:
            merged.append((head, body))

    pre: list[list[str]] = []
    co: list[list[str]] = []
    for head, body in merged:
        hl = head.lower()
        if "recommended" in hl or "preparation" in hl:
            continue
        head_co = "concurrent" in hl or "corequisite" in hl
        for codes, conc in _clauses(body):
            (co if head_co or conc else pre).append(codes)
    out = {}
    if pre:
        out["pre"] = pre
    if co:
        out["co"] = co
    return out


@lru_cache(maxsize=1)
def _data() -> dict[str, dict]:
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}     # no data -> no constraints -> the timeline behaves as before
    out: dict[str, dict] = {}
    # A suffixed twin (MATH 140H) is keyed under its base code only when the base
    # course itself has no entry — the exact course's own rule wins.
    for code in sorted(raw, key=lambda k: norm(k) == k.strip().upper()):
        out[norm(code)] = raw[code]
    return out


def constraints(code: str) -> tuple[list[frozenset], list[frozenset]]:
    """(prerequisite clauses, corequisite clauses) for a course, each clause the
    set of courses any one of which meets it. A course never requires itself."""
    code = norm(code)
    rec = _data().get(code) or {}
    def _sets(key):
        return [s for s in (frozenset(c) - {code} for c in rec.get(key, [])) if s]
    return _sets("pre"), _sets("co")
