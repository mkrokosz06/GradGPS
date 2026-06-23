"""
Parses an unofficial Penn State transcript PDF.
Returns a list of dicts, one per course.

Handles:
  - Completed courses  (earned > 0, grade present)
  - In-progress        (attempted > 0, earned = 0, no grade yet)
  - Transfer credits   (grade = "TR")
  - Failed/forgiven    (earned = 0, grade = F — treated as missing, not counted)
  - W suffix courses   (CHEM 213W normalised to CHEM 213 for catalog matching)
"""

import re
import io
import pdfplumber


# Matches lines like:
#   EDSGN 100 Cornerstone Eng Dsgn 3.000 3.000 A 12.000
#   MATH 140 CALC ANLY GEOM I 4.000 0.000 F 0.000
#   CMPSC 131 PROG & COMP I 3.000 0.000 0.000       ← in-progress (no grade, no points)
#   PLSC 1 Amer. Politics 3.000 3.000 TR 0.000
#
# Strategy: anchor on the numeric columns at the END of the line.
# The department code is always the first token; course number is always second.
COURSE_PATTERN = re.compile(
    r"^([A-Z]{2,6})\s+"           # dept code (EDSGN, CMPSC, FRNSC...)
    r"(\d{1,3}[A-Z]{0,2})\s+"    # course number, optional suffix (131, 415W, 100B)
    r".+?"                         # description — non-greedy, any chars
    r"\s+(\d+\.\d{3})"            # attempted credits  e.g. 3.000
    r"\s+(\d+\.\d{3})"            # earned credits     e.g. 3.000  (0.000 if not done)
    r"(?:\s+([A-DF][+-]?|TR))?"   # grade: A B+ C- D F TR — optional (absent if in-progress)
    r"\s+[\d.]+$",                 # quality points (last column)
    re.MULTILINE
)

# Grades that mean "failed / not completed" — don't count as done
FAILING_GRADES = {"F", "W", "WN", "XF"}


def _normalise_code(code: str) -> str:
    """
    Strip trailing W from course codes so transcript 'CHEM 213W' matches
    catalog entry 'CHEM 213'.  The W suffix is a Writing Across the Curriculum
    designation — the same course, just with a WAC component.
    """
    return re.sub(r"W$", "", code.strip())


def parse_transcript(pdf_bytes: bytes) -> list[dict]:
    """
    Parameters
    ----------
    pdf_bytes : bytes
        Raw bytes of the unofficial PSU transcript PDF.

    Returns
    -------
    list of dicts with keys:
        course_code    str   e.g. "CHEM 110"
        grade          str   e.g. "A", "B+", "TR", or "" if in-progress
        credits_earned float
        term           str   e.g. "FA 2025"
        status         str   "done" | "in_progress" | "transfer"
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]

    full_text = "\n".join(pages_text)
    courses   = []
    seen      = {}   # normalised course_code → index (last/best occurrence wins)

    current_term = "Unknown"
    term_pattern = re.compile(r"\b(FA|SP|SU)\s+(20\d{2})\b")

    for line in full_text.splitlines():
        line = line.strip()

        # Track current term from section headers
        tm = term_pattern.search(line)
        if tm:
            current_term = f"{tm.group(1)} {tm.group(2)}"
            continue

        m = COURSE_PATTERN.match(line)
        if not m:
            continue

        dept      = m.group(1)
        number    = m.group(2)
        attempted = float(m.group(3))
        earned    = float(m.group(4))
        grade     = (m.group(5) or "").strip()

        raw_code  = f"{dept} {number}"
        norm_code = _normalise_code(f"{dept} {number}")  # strip trailing W

        # Determine status
        if grade == "TR":
            status = "transfer"
        elif grade in FAILING_GRADES or (grade and earned == 0):
            status = "failed"    # F, W — don't count toward requirements
        elif earned > 0 and grade:
            status = "done"
        elif attempted > 0:
            status = "in_progress"
        else:
            continue

        # Skip failed courses — they don't satisfy any requirement
        if status == "failed":
            continue

        entry = {
            "course_code":    norm_code,
            "raw_code":       raw_code,
            "grade":          grade,
            "credits_earned": earned,
            "term":           current_term,
            "status":         status,
        }

        # If same normalised code seen before, keep the better one
        # Priority: done > in_progress > transfer
        priority = {"done": 2, "in_progress": 1, "transfer": 0}
        if norm_code in seen:
            existing = courses[seen[norm_code]]
            if priority[status] >= priority[existing["status"]]:
                courses[seen[norm_code]] = entry
        else:
            seen[norm_code] = len(courses)
            courses.append(entry)

    return courses


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python transcript_parser.py path/to/transcript.pdf")
        sys.exit(1)

    with open(path, "rb") as f:
        results = parse_transcript(f.read())

    done        = [c for c in results if c["status"] == "done"]
    in_progress = [c for c in results if c["status"] == "in_progress"]
    transfer    = [c for c in results if c["status"] == "transfer"]

    print(f"\nParsed {len(results)} courses:")
    print(f"  Done:        {len(done)}")
    print(f"  In Progress: {len(in_progress)}")
    print(f"  Transfer:    {len(transfer)}")
    print()

    for c in results:
        flag = {"done": "OK", "in_progress": "IP", "transfer": "TR"}[c["status"]]
        norm = f" (normalised from {c['raw_code']})" if c["raw_code"] != c["course_code"] else ""
        print(f"  [{flag}] {c['course_code']:<14} {c['grade']:<4} {c['term']}{norm}")
