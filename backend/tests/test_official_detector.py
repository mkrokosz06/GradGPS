"""
Tests for official-transcript detection and the official-layout parser.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_official_detector.py -v
  * plain python:  cd backend && python tests/test_official_detector.py

All unit tests are hermetic (no PDF, no PII). An optional end-to-end test runs
only if OFFICIAL_SAMPLE_PDF points at a real official transcript on disk.
"""

import os
import sys

# Make the backend package importable when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from official_detector import detect_official, THRESHOLD
from transcript_parser import (
    _column_lines,
    _normalise_term,
    official_parse_looks_bad,
    parse_transcript,
    parse_and_detect,
    COURSE_PATTERN,
    FULL_TERM_PATTERN,
    ABBR_TERM_PATTERN,
)


# ── Detector: text signals ──────────────────────────────────────────────────

def test_unofficial_marker_vetoes():
    text = "UNOFFICIAL TRANSCRIPT\nName: Test Student\nOffice of the University Registrar"
    d = detect_official(b"%PDF-1.4 plain", text)
    assert d.is_official is False
    assert "unofficial_marker" in d.signals


def test_official_text_without_signature_still_detected():
    # Printed/scanned official (no digital signature bytes): header + registrar.
    text = (
        "Undergraduate Official Transcript\n"
        "Office of the University Registrar\n"
        "University seal\n"
    )
    d = detect_official(b"%PDF-1.4 plain", text)
    assert d.is_official is True            # 3 (header) + 2 (registrar cap) = 5
    assert "official_header" in d.signals
    assert "registrar_language" in d.signals


def test_negative_lookbehind_header_not_fired_on_unofficial():
    text = "UNOFFICIAL TRANSCRIPT"
    d = detect_official(b"", text)
    assert "official_header" not in d.signals   # lookbehind blocks UNOFFICIAL


def test_registrar_boilerplate_alone_not_official():
    text = "Office of the University Registrar\nFamily Educational Rights and Privacy Act"
    d = detect_official(b"%PDF-1.4 plain", text)
    assert d.score < THRESHOLD                  # capped at 2
    assert d.is_official is False


# ── Detector: byte signature (layout-agnostic) ──────────────────────────────

def test_signature_bytes_alone_detected():
    # Empty text, but the certified-PDF byte markers are present.
    pdf_bytes = b"%PDF-1.6 ... /ByteRange [0 100 200 300] ... adbe.pkcs7.detached ..."
    d = detect_official(pdf_bytes, "")
    assert d.is_official is True
    assert "pdf_digital_signature" in d.signals


def test_signature_does_not_rely_on_spaced_type_sig():
    # Regression guard: the real sample has "/Type/Sig" (no space). Detection must
    # not depend on the spaced form — /ByteRange + adbe.pkcs7 is the anchor.
    pdf_bytes = b"/Type/Sig /ByteRange[0 1 2 3] adbe.pkcs7.detached"
    assert b"/Type /Sig" not in pdf_bytes
    d = detect_official(pdf_bytes, "")
    assert d.is_official is True


def test_partial_signature_bytes_not_detected():
    # /ByteRange without the pkcs7 marker should NOT trip the signature signal.
    d = detect_official(b"/ByteRange only", "")
    assert "pdf_digital_signature" not in d.signals


# ── Official parser: two-column de-interleave ───────────────────────────────

def _word(text, x0, top):
    return {"text": text, "x0": float(x0), "x1": float(x0) + 10, "top": float(top)}


def test_column_lines_deinterleaves_side_by_side_courses():
    # Two different courses printed on the same visual row, one per column.
    # Left col x0 < 396, right col x0 >= 396.
    left  = ["CHEM", "110", "Chem", "Princ", "3.000", "3.000", "B-", "8.010"]
    right = ["MATH", "141", "Calc", "II", "4.000", "4.000", "B+", "13.320"]
    words = []
    for i, t in enumerate(left):
        words.append(_word(t, 72 + i * 30, 100))
    for i, t in enumerate(right):
        words.append(_word(t, 420 + i * 30, 100))

    left_lines  = _column_lines(words, 0, 396)
    right_lines = _column_lines(words, 396, 792)

    assert COURSE_PATTERN.match(left_lines[0]).group(1) == "CHEM"
    assert COURSE_PATTERN.match(right_lines[0]).group(1) == "MATH"
    # The two courses never collide onto one line.
    assert "MATH" not in left_lines[0]
    assert "CHEM" not in right_lines[0]


# ── Term normalisation (full-name vs abbreviated) ───────────────────────────

def test_full_name_term_normalised():
    assert _normalise_term(FULL_TERM_PATTERN.search("Fall 2025")) == "FA 2025"
    assert _normalise_term(FULL_TERM_PATTERN.search("Spring 2026")) == "SP 2026"
    assert _normalise_term(FULL_TERM_PATTERN.search("Summer 2024")) == "SU 2024"


def test_abbreviated_term_still_works():
    assert _normalise_term(ABBR_TERM_PATTERN.search("FA 2025")) == "FA 2025"


# ── Safety net ──────────────────────────────────────────────────────────────

def _course(term):
    return {"course_code": "X 1", "term": term, "status": "done"}


def test_safety_net_flags_too_few_courses():
    assert official_parse_looks_bad([_course("FA 2025")]) is True


def test_safety_net_flags_many_unknown_terms():
    courses = [_course("Unknown")] * 4 + [_course("FA 2025")] * 6   # 40% unknown
    assert official_parse_looks_bad(courses) is True


def test_safety_net_passes_clean_parse():
    courses = [_course("FA 2025")] * 10
    assert official_parse_looks_bad(courses) is False


# ── Unofficial parser regression ────────────────────────────────────────────

def test_unofficial_parse_unchanged():
    sample = (
        "FA 2025\n"
        "EDSGN 100 Cornerstone Eng Dsgn 3.000 3.000 A 12.000\n"
        "MATH 140 CALC ANLY GEOM I 4.000 0.000 F 0.000\n"       # failed -> dropped
        "CMPSC 131 PROG & COMP I 3.000 0.000 0.000\n"           # in-progress
        "IST 440W Integration Backgrnd 3.000 3.000 B+ 9.990\n"  # W -> writing
        "SP 2026\n"
        "PLSC 1 Amer. Politics 3.000 3.000 TR 0.000\n"          # transfer
    )
    courses = parse_transcript(b"", pages_text=[sample])
    by_code = {c["course_code"]: c for c in courses}
    assert set(by_code) == {"EDSGN 100", "CMPSC 131", "IST 440", "PLSC 1"}
    assert by_code["EDSGN 100"]["status"] == "done"
    assert by_code["EDSGN 100"]["term"] == "FA 2025"
    assert by_code["CMPSC 131"]["status"] == "in_progress"
    assert by_code["IST 440"]["is_writing"] is True
    assert by_code["PLSC 1"]["status"] == "transfer"
    assert by_code["PLSC 1"]["term"] == "SP 2026"


# ── Optional end-to-end (needs a real official sample; skipped otherwise) ────

def test_real_official_sample_end_to_end():
    path = os.getenv("OFFICIAL_SAMPLE_PDF")
    if not path or not os.path.exists(path):
        _skip("set OFFICIAL_SAMPLE_PDF to a real official transcript to run this")
        return
    raw = open(path, "rb").read()
    courses, detection = parse_and_detect(raw)
    assert detection.is_official is True
    assert official_parse_looks_bad(courses) is False
    # No mangled codes (watermark letters spliced in) and no Unknown terms.
    import re
    assert not [c for c in courses if re.search("[a-z]", c["course_code"])]
    assert not [c for c in courses if c["term"] in (None, "", "Unknown")]


# ── Tiny runner so this works without pytest installed ──────────────────────

def _skip(reason):
    try:
        import pytest
        pytest.skip(reason)
    except ImportError:
        print(f"  SKIP: {reason}")


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
