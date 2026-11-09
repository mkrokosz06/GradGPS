"""
LER -> LHR rename (Labor and Employment Relations -> Labor and Human Resources).

Older catalog rows say LER, current transcripts say LHR, and older students'
transcripts say LER. Same number, same course, so either should satisfy the
other. LER courses that still exist under LER (424, 425, 485, ...) must not be
aliased to anything.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_ler_lhr_rename.py -v
  * plain python:  cd backend && python tests/test_ler_lhr_rename.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_engine import run_audit, _COURSE_ALIASES


def _tx(code, status="done", grade="A"):
    return {"course_code": code, "status": status, "grade": grade, "credits_earned": 3}


def _req(code):
    return [{"program_name": "X", "requirement_group": "Major", "group_type": "required",
             "course_code": code, "credits": 3}]


def _done(rows, tx):
    a = run_audit(rows, tx)
    return a["missing"] == 0 and a["in_progress"] == 0


def test_lhr_transcript_satisfies_ler_requirement():
    assert _done(_req("LER 100"), [_tx("LHR 100")])


def test_ler_transcript_satisfies_lhr_requirement():
    assert _done(_req("LHR 460"), [_tx("LER 460")])


def test_y_suffixed_course_renames():
    assert _done(_req("LER 458Y"), [_tx("LHR 458Y")])


def test_honors_twin_matches_storage_form():
    # LHR 475H is stored as 'LHR 475' by the parser.
    assert _done(_req("LER 475"), [_tx("LHR 475")])


def test_live_ler_courses_are_not_aliased():
    for n in ("424", "425", "485", "488", "489"):
        assert f"LER {n}" not in _COURSE_ALIASES


def test_different_number_does_not_match():
    assert not _done(_req("LER 100"), [_tx("LHR 201")])


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
           if n.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} passed")
