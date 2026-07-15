"""
Tests for University Park program scoping (routers/programs.is_up_program).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_programs_scope.py -v
  * plain python:  cd backend && python tests/test_programs_scope.py

Hermetic — the pure scoping predicate only, no DynamoDB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.programs import is_up_program, _UP_COLLEGE_QUALIFIERS


def test_unqualified_program_is_up():
    # The majority of programs have no parenthetical → University Park.
    assert is_up_program("Actuarial Science, B.S.")
    assert is_up_program("Aerospace Engineering, B.S.")
    assert is_up_program("Accounting, B.S. (Business)")


def test_up_college_parenthetical_is_up():
    assert is_up_program("Psychology, B.S. (Liberal Arts)")
    assert is_up_program("Biology, B.S. (Science)")
    assert is_up_program("Kinesiology, B.S. (Health and Human Development)")


def test_branch_campus_parenthetical_excluded():
    assert not is_up_program("Accounting, B.S. (Capital)")
    assert not is_up_program("Business, B.S. (University College)")


def test_exhaustive_campus_list_catches_campuses_not_in_catalog():
    # These campuses aren't in the current catalog but must be excluded so a
    # future re-scrape can't leak them.
    for campus in ("Berks", "Abington", "Altoona", "Behrend", "Harrisburg", "York"):
        assert not is_up_program(f"Some Program, B.S. ({campus})"), campus


def test_up_college_qualifiers_are_never_treated_as_campuses():
    # A parenthetical that is a known UP college must always pass.
    for college in _UP_COLLEGE_QUALIFIERS:
        title = college.title() if college != "k-12" else "K-12"
        assert is_up_program(f"Some Program, B.S. ({title})"), college


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
