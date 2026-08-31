"""
Tests for transcript_parser course-line parsing and accumulation rules.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_transcript_parser.py -v
  * plain python:  cd backend && python tests/test_transcript_parser.py

Hermetic — feeds synthetic page text through parse_transcript (the unofficial
path), which shares COURSE_PATTERN / _make_entry / _accumulate with the
official parser, so these rules are covered for both.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transcript_parser import parse_transcript, _normalise_code


def _parse(text: str):
    return parse_transcript(b"", pages_text=[text])


# ── normalisation ────────────────────────────────────────────────────────────

def test_normalise_strips_attr_suffix_after_digit_only():
    assert _normalise_code("IST 440W") == "IST 440"
    assert _normalise_code("ENGL 30H") == "ENGL 30"
    assert _normalise_code("SOC 119N") == "SOC 119"
    assert _normalise_code("CAS 100A") == "CAS 100A"     # section letter kept
    # XFR placeholder codes keep their gen-ed attribute letters intact.
    assert _normalise_code("XFRGH") == "XFRGH"
    assert _normalise_code("XFRGHA") == "XFRGHA"


# ── XFR generic transfer/test credit rows ────────────────────────────────────

def test_xfr_transfer_rows_are_parsed():
    # Real-layout rows from a signed official transcript (ACE + AP test credit).
    text = """
FA 2024
ENGL XFRGH Transfer Credit GH 6.000 6.000 TR 0.000
NUTR XFRGHA Transfer Credit 3.000 3.000 TR 0.000
"""
    courses = _parse(text)
    by = {c["course_code"]: c for c in courses}
    assert by["ENGL XFRGH"]["status"] == "transfer"
    assert by["ENGL XFRGH"]["credits_earned"] == 6.0
    assert by["NUTR XFRGHA"]["credits_earned"] == 3.0


def test_generic_transfer_placeholder_sums_within_same_term():
    # A school can send several separate general-transfer awards under the SAME
    # placeholder code in the SAME term (real case: Ohio Univ, 2+3+3 = 8 cr).
    # These are credit buckets, not a layout duplicate, so they must sum.
    text = """
Transfer Credit from Ohio Univ
Spring 2026
TRN XFRGEN TRN - General Transfer Credit 2.000 2.000 TR 0.000
TRN XFRGEN TRN - General Transfer Credit 3.000 3.000 TR 0.000
TRN XFRGEN TRN - General Transfer Credit 3.000 3.000 TR 0.000
"""
    courses = _parse(text)
    assert len(courses) == 1
    assert courses[0]["course_code"] == "TRN XFRGEN"
    assert courses[0]["credits_earned"] == 8.0
    assert courses[0]["status"] == "transfer"


# ── AP / test credit (Test Credits section) ──────────────────────────────────

def test_ap_test_credit_granted_course_is_parsed():
    # AP/test credit renders the granted PSU course with a SINGLE credit column
    # and a TR grade, no earned/quality-points columns. It must still be counted
    # (as transfer credit), applied to the term it was transferred to.
    text = """
Test Credits
Advanced Placement Mathematics: Calculus AB 01/01/2024 5.00
Transferred to Term FA 2024 as
MATH 140 CALC ANLY GEOM I 4.000 TR
"""
    courses = _parse(text)
    assert len(courses) == 1
    c = courses[0]
    assert c["course_code"] == "MATH 140"
    assert c["status"] == "transfer"
    assert c["credits_earned"] == 4.0
    assert c["term"] == "FA 2024"


def test_normal_transfer_row_not_matched_as_test_credit():
    # A full transfer row ends in quality points, not TR — it must parse via the
    # normal path (both credit columns), not be mis-caught by the test-credit rule.
    text = """
Transfer Credit from Somewhere
Spring 2026
ART 1 Intro Vis Arts 3.000 3.000 TR 0.000
"""
    courses = _parse(text)
    assert len(courses) == 1
    assert courses[0]["course_code"] == "ART 1"
    assert courses[0]["credits_earned"] == 3.0


# ── repeatable courses (same code, different terms) ──────────────────────────

def test_repeatable_course_credits_are_summed_across_terms():
    # ENGR 297 special topics taken twice: 0.25cr one term, 1cr another —
    # PSU counts both, so the single stored entry must carry 1.25 credits.
    text = """
SP 2024
ENGR 297 Special Topics 0.250 0.250 A 1.000
FA 2024
ENGR 297 Special Topics 1.000 1.000 A 4.000
"""
    courses = _parse(text)
    assert len(courses) == 1
    assert courses[0]["course_code"] == "ENGR 297"
    assert courses[0]["credits_earned"] == 1.25
    assert courses[0]["status"] == "done"


def test_same_term_duplicate_still_dedupes():
    # The same course printed twice in ONE term is a layout duplicate, not a
    # repeat — credits must not be summed.
    text = """
FA 2024
MATH 140 CALC ANLY GEOM 4.000 4.000 B+ 13.320
MATH 140 CALC ANLY GEOM 4.000 4.000 B+ 13.320
"""
    courses = _parse(text)
    assert len(courses) == 1
    assert courses[0]["credits_earned"] == 4.0


def test_done_beats_in_progress_not_summed():
    # A retaken/completed course that also shows an in-progress row keeps the
    # done instance only (status priority, no credit summing).
    text = """
SP 2025
CMPSC 131 PROG & COMP I 3.000 3.000 D 3.000
FA 2025
CMPSC 131 PROG & COMP I 3.000 0.000 0.000
"""
    courses = _parse(text)
    assert len(courses) == 1
    assert courses[0]["status"] == "done"
    assert courses[0]["credits_earned"] == 3.0


def test_grade_replacement_excluded_attempt_dropped():
    # PSU zeroes the earned credits of a replaced attempt — it parses as failed
    # and is dropped, so only the counting attempt contributes credits.
    text = """
SP 2025
CHEM 110 Chemical Principles 3.000 0.000 F 0.000
FA 2025
CHEM 110 Chemical Principles 3.000 3.000 B 9.000
"""
    courses = _parse(text)
    assert len(courses) == 1
    assert courses[0]["credits_earned"] == 3.0
    assert courses[0]["grade"] == "B"


def test_quarter_credit_course_parses():
    text = """
FA 2024
ENGR 297 Special Topics 0.250 0.250 A 1.000
"""
    courses = _parse(text)
    assert len(courses) == 1 and courses[0]["credits_earned"] == 0.25


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {t.__name__}: {e!r}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
