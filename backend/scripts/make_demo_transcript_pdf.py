"""
Generate the synthetic sample transcript PDF used for App Review.

WHY: the reviewer needs to exercise the transcript-upload flow, and cannot be
asked to produce a real Penn State transcript. This writes a *fabricated*
LionPATH-style unofficial transcript to scripts/demo_assets/, built from the
exact same course list as scripts/seed_demo_account.py -- so uploading it is
idempotent: it reproduces the account the reviewer is already looking at
instead of wiping it.

It is deliberately marked UNOFFICIAL (which is also official_detector's hard
veto, so it can never trip the official-transcript 409 consent gate) and is not
signed. It contains no real person's record.

    python scripts/make_demo_transcript_pdf.py [--out PATH] [--verify]

--verify re-parses the written PDF through transcript_parser and prints what
came out, which is the only meaningful test of this file.
"""

import argparse
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from seed_demo_account import TRANSCRIPT, DEMO_NAME, MAJOR, _bulletin, _DONE

# Fabricated -- deliberately not in PSU's 9-digit format.
DEMO_STUDENT_ID = "DEMO-0000000"

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "demo_assets", "demo_transcript.pdf")

_GRADE_POINTS = {
    "A": 4.0, "A-": 3.67, "B+": 3.33, "B": 3.0, "B-": 2.67,
    "C+": 2.33, "C": 2.0, "C-": 1.67, "D": 1.0, "F": 0.0,
}

# Term order for grouping (matches the transcript's natural order).
_SEASON_ORDER = {"SP": 0, "SU": 1, "FA": 2}


def _term_key(term):
    season, year = term.split()
    return (int(year), _SEASON_ORDER.get(season, 3))


def _rows():
    """(term, [line, ...]) in transcript order, in the LionPATH column layout
    transcript_parser.COURSE_PATTERN anchors on:

        <DEPT> <NUM> <Title> <attempted> <earned> [grade] <quality points>
    """
    bul = _bulletin()
    by_term = {}
    for code, grade, credits, term, status in TRANSCRIPT:
        meta = bul.get(code) or {}
        cr = float(meta.get("credits") or credits)
        title = (meta.get("title") or code)
        # Keep the title free of digits/periods so the numeric columns at the
        # end of the line stay unambiguous for the parser.
        title = "".join(ch for ch in title if ch.isalpha() or ch in " &-/")
        title = " ".join(title.split())[:38] or code
        earned = cr if status == _DONE else 0.0
        points = _GRADE_POINTS.get(grade, 0.0) * earned
        line = "%s %s %.3f %.3f%s %.3f" % (
            code, title, cr, earned,
            (" " + grade) if grade else "",
            points,
        )
        by_term.setdefault(term, []).append(line)
    return sorted(by_term.items(), key=lambda kv: _term_key(kv[0]))


def write_pdf(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter
    y = height - 54

    def line(text, font="Helvetica", size=8.5, dy=12):
        nonlocal y
        if y < 60:
            c.showPage()
            y = height - 54
        c.setFont(font, size)
        c.drawString(54, y, text)
        y -= dy

    line("UNOFFICIAL ACADEMIC TRANSCRIPT", "Helvetica-Bold", 12, 18)
    line("SAMPLE DOCUMENT - SYNTHETIC DATA - NOT A REAL STUDENT RECORD",
         "Helvetica-Bold", 8.5, 16)
    line("Name: %s" % DEMO_NAME)
    line("Student ID: %s" % DEMO_STUDENT_ID)
    line("Program: %s" % MAJOR)
    line("Campus: University Park", dy=18)

    total_att = total_earn = 0.0
    for term, lines in _rows():
        line(term, "Helvetica-Bold", 9.5, 14)
        line("Course            Description                       Attempted  Earned  Grade  Points",
             "Helvetica-Oblique", 7.5, 11)
        for text in lines:
            line(text, "Courier", 8.5, 11)
            parts = text.split()
            total_att += float(parts[-3]) if len(parts) >= 3 else 0.0
        y -= 6

    line("", dy=10)
    line("END OF UNOFFICIAL TRANSCRIPT", "Helvetica-Bold", 8.5, 12)
    c.save()
    return path


def verify(path):
    from transcript_parser import parse_and_detect
    with open(path, "rb") as f:
        data = f.read()
    result = parse_and_detect(data)
    courses = result[0] if isinstance(result, tuple) else result
    detection = result[1] if isinstance(result, tuple) and len(result) > 1 else None

    print("\nRe-parsed %s" % path)
    if detection is not None:
        print("  official detection: %s" % (detection,))
    print("  %d courses parsed" % len(courses))
    by_term = {}
    for co in courses:
        by_term.setdefault(co["term"], []).append(co)
    for term in sorted(by_term, key=_term_key):
        rows = by_term[term]
        print("  %-9s %2d  %s" % (term, len(rows),
                                  ", ".join(r["course_code"] for r in rows)))

    expected = {code for code, *_ in TRANSCRIPT}
    got = {co["course_code"] for co in courses}
    missing, extra = sorted(expected - got), sorted(got - expected)
    bad_term = [co["course_code"] for co in courses if co["term"] == "Unknown"]
    ok = not missing and not extra and not bad_term
    if missing:
        print("  MISSING: %s" % missing)
    if extra:
        print("  UNEXPECTED: %s" % extra)
    if bad_term:
        print("  UNKNOWN TERM: %s" % bad_term)
    print("  RESULT: %s" % ("OK" if ok else "MISMATCH"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    path = write_pdf(args.out)
    print("Wrote %s (%d bytes)" % (path, os.path.getsize(path)))
    if args.verify and not verify(path):
        sys.exit(1)


if __name__ == "__main__":
    main()
