"""
Parses Penn State transcript PDFs (unofficial *and* official layouts).

Entry point
-----------
`parse_and_detect(pdf_bytes)` extracts text once, detects whether the PDF is an
official transcript (see official_detector), and routes to the matching parser:
  - unofficial (LionPATH browser-print)  -> parse_transcript()
  - official   (registrar, signed/print) -> parse_official_transcript()
Both return the same list-of-dicts shape.

Handles:
  - Completed courses  (earned > 0, grade present)
  - In-progress        (attempted > 0, earned = 0, no grade yet)
  - Transfer credits   (grade = "TR")
  - Failed/forgiven    (earned = 0, grade = F — treated as missing, not counted)
  - W suffix courses   (CHEM 213W normalised to CHEM 213 for catalog matching)
"""

import re
import io
import logging
import pdfplumber

# pdfminer.six (under pdfplumber) emits an enormous volume of DEBUG log records
# while parsing — one per glyph/object. If the host process configures the root
# logger to process DEBUG (as uvicorn's console logging can), formatting and
# emitting those records dominates parse time (350 ms -> 2.5-5 s on a real
# transcript). Cap these libraries at WARNING so parsing is fast regardless of
# how the surrounding app configures logging.
logging.getLogger("pdfminer").setLevel(logging.WARNING)
logging.getLogger("pdfplumber").setLevel(logging.WARNING)


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

# Term headers.
#   Unofficial abbreviates:  "FA 2025"
#   Official spells it out:  "Fall 2025"
ABBR_TERM_PATTERN = re.compile(r"\b(FA|SP|SU)\s+(20\d{2})\b")
FULL_TERM_PATTERN = re.compile(r"\b(Fall|Spring|Summer)\s+(20\d{2})\b")
_FULL_SEASON = {"Fall": "FA", "Spring": "SP", "Summer": "SU"}

# Hard cap on pages we will extract text from. Real PSU transcripts run a handful
# of pages; a document with hundreds/thousands of pages is a PDF bomb, not a
# transcript. Capping bounds worst-case parse cost.
MAX_PAGES = 50

# Official transcripts carry a large diagonal "Copy of Transcript" watermark.
# Its glyphs are rendered at ~16.7–22.2 pt while every real character is 6–9 pt,
# so a size threshold cleanly separates the watermark from the course tables.
# (Validated against a real signed sample.)
_WATERMARK_MIN_SIZE = 12.0

# Priority when the same normalised course code appears more than once.
_STATUS_PRIORITY = {"done": 2, "in_progress": 1, "transfer": 0}


def _normalise_code(code: str) -> str:
    """
    Strip trailing PSU attribute-designation suffixes from course codes so
    transcript variants match their base catalog entry:
      W  — Writing Across the Curriculum  (e.g. IST 440W  → IST 440)
      H  — Honors section                 (e.g. ENGL 30H  → ENGL 30)
      N  — Non-Western / Diversity attr   (e.g. SOC 119N  → SOC 119)

    Section letters (A/B/C in CAS 100A, 100B, 100C) are intentionally kept —
    those are distinct catalog entries, not attribute designations.
    """
    return re.sub(r"[WHN]$", "", code.strip())


def _normalise_term(match: re.Match) -> str:
    """Turn either 'FA 2025' or 'Fall 2025' into the internal 'FA 2025' form."""
    season = _FULL_SEASON.get(match.group(1), match.group(1))
    return f"{season} {match.group(2)}"


def _make_entry(dept: str, number: str, attempted: float, earned: float,
                grade: str, term: str) -> dict | None:
    """
    Build a course entry dict from parsed fields, or None if the row should be
    skipped (failed/forgiven, or no attempted credits). Shared by both parsers.
    """
    if grade == "TR":
        status = "transfer"
    elif grade in FAILING_GRADES or (grade and earned == 0):
        status = "failed"          # F, W — don't count toward requirements
    elif earned > 0 and grade:
        status = "done"
    elif attempted > 0:
        status = "in_progress"
    else:
        return None

    if status == "failed":
        return None

    raw_code  = f"{dept} {number}"
    norm_code = _normalise_code(raw_code)
    return {
        "course_code":    norm_code,
        "raw_code":       raw_code,
        "grade":          grade,
        "credits_earned": earned,
        "term":           term,
        "status":         status,
        # Writing Across the Curriculum designation: a W/M/X/Y suffix on the
        # course number. Captured here because norm_code strips the W.
        "is_writing":     bool(re.search(r"[WMXY]$", number.strip().upper())),
    }


def _accumulate(courses: list[dict], seen: dict[str, int], entry: dict) -> None:
    """
    Add `entry` to `courses`, deduping by normalised code. When the same course
    appears twice, keep the higher-priority status (done > in_progress > transfer).
    """
    norm_code = entry["course_code"]
    if norm_code in seen:
        existing = courses[seen[norm_code]]
        if _STATUS_PRIORITY[entry["status"]] >= _STATUS_PRIORITY[existing["status"]]:
            courses[seen[norm_code]] = entry
    else:
        seen[norm_code] = len(courses)
        courses.append(entry)


def extract_pages_text(pdf_bytes: bytes) -> list[str]:
    """Extract per-page text (up to MAX_PAGES) from a transcript PDF."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages[:MAX_PAGES]]


def parse_transcript(pdf_bytes: bytes, *, pages_text: list[str] | None = None) -> list[dict]:
    """
    Parse an *unofficial* (LionPATH browser-print) transcript.

    Parameters
    ----------
    pdf_bytes : bytes
        Raw bytes of the transcript PDF.
    pages_text : list[str], optional
        Pre-extracted page text (from extract_pages_text). Extracted here if omitted,
        so callers that already have the text don't pay for a second extraction.

    Returns
    -------
    list of dicts with keys:
        course_code, raw_code, grade, credits_earned, term, status, is_writing
    """
    if pages_text is None:
        pages_text = extract_pages_text(pdf_bytes)

    full_text = "\n".join(pages_text)
    courses: list[dict] = []
    seen: dict[str, int] = {}

    current_term = "Unknown"

    for line in full_text.splitlines():
        line = line.strip()

        # Track current term from section headers.
        tm = ABBR_TERM_PATTERN.search(line) or FULL_TERM_PATTERN.search(line)
        if tm:
            current_term = _normalise_term(tm)
            continue

        m = COURSE_PATTERN.match(line)
        if not m:
            continue

        entry = _make_entry(
            dept=m.group(1), number=m.group(2),
            attempted=float(m.group(3)), earned=float(m.group(4)),
            grade=(m.group(5) or "").strip(), term=current_term,
        )
        if entry is not None:
            _accumulate(courses, seen, entry)

    return courses


def _column_lines(words: list[dict], lo: float, hi: float) -> list[str]:
    """
    Reconstruct visual text lines from the words whose x0 falls in [lo, hi).
    Words are grouped into rows by their (rounded) vertical position and joined
    left-to-right. This de-interleaves the official transcript's two side-by-side
    term columns, which extract_text() would otherwise splice together.
    """
    rows: dict[int, list[dict]] = {}
    for w in words:
        if lo <= w["x0"] < hi:
            rows.setdefault(round(w["top"] / 3), []).append(w)

    lines = []
    for key in sorted(rows):
        ordered = sorted(rows[key], key=lambda w: w["x0"])
        lines.append(" ".join(w["text"] for w in ordered))
    return lines


def parse_official_transcript(pdf_bytes: bytes) -> list[dict]:
    """
    Parse an *official* PSU transcript (registrar-issued, signed or printed).

    Official transcripts differ from unofficial ones in three ways that break the
    plain-text parser, all handled here:
      1. Two term columns side by side  -> split words by x-position, rebuild lines
                                            per column (see _column_lines).
      2. Diagonal "Copy of Transcript" watermark spliced into the course tables
                                         -> drop glyphs >= _WATERMARK_MIN_SIZE pt.
      3. Full-name terms ("Fall 2025")  -> normalised via FULL_TERM_PATTERN.

    Returns the same dict shape as parse_transcript.
    """
    courses: list[dict] = []
    seen: dict[str, int] = {}

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:MAX_PAGES]:
            # Drop the oversized watermark glyphs; keep every non-char object and
            # all normal-size text. Rebuild words from what remains.
            filtered = page.filter(
                lambda obj: obj.get("object_type") != "char"
                or (obj.get("size") or 0) < _WATERMARK_MIN_SIZE
            )
            words = filtered.extract_words(use_text_flow=False)
            mid = page.width / 2

            # Left column, then right column. Term headers appear inside each
            # column, so the "current term" is tracked per column independently.
            for lo, hi in ((0.0, mid), (mid, page.width)):
                current_term = "Unknown"
                for line in _column_lines(words, lo, hi):
                    tm = FULL_TERM_PATTERN.search(line) or ABBR_TERM_PATTERN.search(line)
                    if tm:
                        current_term = _normalise_term(tm)
                        # A header line almost never also carries a course row;
                        # fall through in case the layout ever combines them.

                    m = COURSE_PATTERN.match(line)
                    if not m:
                        continue

                    entry = _make_entry(
                        dept=m.group(1), number=m.group(2),
                        attempted=float(m.group(3)), earned=float(m.group(4)),
                        grade=(m.group(5) or "").strip(), term=current_term,
                    )
                    if entry is not None:
                        _accumulate(courses, seen, entry)

    return courses


def official_parse_looks_bad(courses: list[dict]) -> bool:
    """
    Trustworthiness safety net for the official parser (built/tuned from a single
    sample — the two-column de-interleave can fail on layouts we haven't seen).
    Returns True when the result is too suspect to store, so the caller can fall
    back to asking the user for their unofficial transcript instead.
    """
    if len(courses) < 3:
        return True   # implausibly few for a full official record
    unknown = sum(1 for c in courses if c.get("term") in (None, "", "Unknown"))
    return unknown / len(courses) > 0.3   # too many unresolved terms => de-interleave failed


def detect_kind(pdf_bytes: bytes):
    """
    Cheap first pass: extract text once and classify official vs. unofficial,
    WITHOUT running the (slower) course parser. Lets the upload route return the
    consent-gate 409 immediately, before doing any parsing work.

    Returns
    -------
    (detection, pages_text) : tuple[official_detector.OfficialDetection, list[str]]
    """
    from official_detector import detect_official

    pages_text = extract_pages_text(pdf_bytes)
    detection  = detect_official(pdf_bytes, "\n".join(pages_text))
    return detection, pages_text


def parse_with_detection(pdf_bytes: bytes, detection, pages_text: list[str] | None = None) -> list[dict]:
    """Parse with the parser matching a detection from detect_kind()."""
    if detection.is_official:
        return parse_official_transcript(pdf_bytes)
    return parse_transcript(pdf_bytes, pages_text=pages_text)


def parse_and_detect(pdf_bytes: bytes):
    """
    Convenience entry point (CLI/tests): detect then parse in one call.
    The upload route instead calls detect_kind() + parse_with_detection()
    separately so it can gate with a 409 between the two.

    Returns
    -------
    (courses, detection) : tuple[list[dict], official_detector.OfficialDetection]
    """
    detection, pages_text = detect_kind(pdf_bytes)
    courses = parse_with_detection(pdf_bytes, detection, pages_text)
    return courses, detection


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("Usage: python transcript_parser.py path/to/transcript.pdf")
        sys.exit(1)

    with open(path, "rb") as f:
        raw = f.read()

    results, detection = parse_and_detect(raw)

    done        = [c for c in results if c["status"] == "done"]
    in_progress = [c for c in results if c["status"] == "in_progress"]
    transfer    = [c for c in results if c["status"] == "transfer"]

    kind = "OFFICIAL" if detection.is_official else "unofficial"
    print(f"\nDetected: {kind}  (score={detection.score}, signals={detection.signals})")
    print(f"Parsed {len(results)} courses:")
    print(f"  Done:        {len(done)}")
    print(f"  In Progress: {len(in_progress)}")
    print(f"  Transfer:    {len(transfer)}")
    if detection.is_official:
        print(f"  Looks bad?   {official_parse_looks_bad(results)}")
    print()

    for c in results:
        flag = {"done": "OK", "in_progress": "IP", "transfer": "TR"}[c["status"]]
        norm = f" (normalised from {c['raw_code']})" if c["raw_code"] != c["course_code"] else ""
        print(f"  [{flag}] {c['course_code']:<14} {c['grade']:<4} {c['term']}{norm}")
