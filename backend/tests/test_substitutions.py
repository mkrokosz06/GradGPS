"""
Tests for course substitutions — "the class I took counts for that requirement".

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_substitutions.py -v
  * plain python:  cd backend && python tests/test_substitutions.py

Hermetic — exercises the taken-set plumbing (audit engine + SAP matcher) and the
code validation, no DynamoDB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_engine import run_audit, run_gen_ed_audit
from sap_schedule import build_taken_set
from substitutions import is_valid_code, norm_code


def _req(code, group="Core", gtype="required", **extra):
    return {
        "program_name": "X", "requirement_group": group,
        "group_type": gtype, "course_code": code, "credits": 3, **extra,
    }


def _tx(code, status="done", grade="A", credits=3):
    return {"course_code": code, "status": status, "grade": grade,
            "credits_earned": credits}


def _status(result, code):
    for g in result["groups"]:
        for src in (g.get("sub_groups") or [g]):
            for item in src["items"]:
                if item["course_code"] == code:
                    return item["status"]
    return None


# ── The taken-set plumbing ───────────────────────────────────────────────────

def test_substitution_satisfies_a_missing_requirement():
    """The Connor case in general form: a course the catalog has no equivalence
    for is declared to count, and the requirement stops being missing."""
    rows = [_req("ETI 302")]
    tx   = [_tx("PHIL 103")]

    assert _status(run_audit(rows, tx), "ETI 302") == "missing"

    result = run_audit(rows, tx, {"ETI 302": "PHIL 103"})
    assert _status(result, "ETI 302") == "done"
    assert result["missing"] == 0
    # Credit comes from the course actually taken, not the requirement row.
    assert result["credits_earned"] == 3.0


def test_substitution_needs_the_course_on_the_transcript():
    """A declaration naming a course the student doesn't have satisfies nothing —
    otherwise any requirement could be waved away by typing a code."""
    rows = [_req("ETI 302")]
    tx   = [_tx("PHIL 103")]
    assert _status(run_audit(rows, tx, {"ETI 302": "NOPE 999"}), "ETI 302") == "missing"
    assert "ETI 302" not in build_taken_set(tx, {"ETI 302": "NOPE 999"})


def test_substitution_never_overrides_a_real_course():
    """If the student actually took the requirement, their own grade/credits win
    over a substitute's — the substitution only ever fills an empty slot."""
    rows = [_req("ETI 302")]
    tx   = [_tx("ETI 302", grade="B", credits=3), _tx("PHIL 103", grade="A", credits=4)]
    result = run_audit(rows, tx, {"ETI 302": "PHIL 103"})
    assert _status(result, "ETI 302") == "done"
    assert result["credits_earned"] == 3.0   # ETI 302's own credits, not PHIL 103's


def test_substitution_respects_min_grade():
    """A substitute is graded like any other course filling the slot."""
    rows = [_req("ETI 302", min_grade="C")]
    tx   = [_tx("PHIL 103", grade="D")]
    assert _status(run_audit(rows, tx, {"ETI 302": "PHIL 103"}), "ETI 302") == "missing"


def test_in_progress_substitute_reads_as_in_progress():
    rows = [_req("ETI 302")]
    tx   = [_tx("PHIL 103", status="in_progress", grade="")]
    assert _status(run_audit(rows, tx, {"ETI 302": "PHIL 103"}), "ETI 302") == "in_progress"


def test_substitution_satisfies_a_choose_one_pair():
    """Declaring against either alternative satisfies the pair."""
    rows = [_req("MATH 110", gtype="choose_one", pair_group_id="900"),
            _req("MATH 140", gtype="choose_one", pair_group_id="900")]
    tx   = [_tx("PHIL 103")]
    assert run_audit(rows, tx)["missing"] == 1
    assert run_audit(rows, tx, {"MATH 110": "PHIL 103"})["missing"] == 0


def test_substitution_applies_to_the_gen_ed_audit():
    rows = [_req("GA 100", group="GA: Arts")]
    tx   = [_tx("PHIL 103")]
    assert run_gen_ed_audit(rows, tx)["groups"][0]["satisfied"] is False
    assert run_gen_ed_audit(rows, tx, {"GA 100": "PHIL 103"})["groups"][0]["satisfied"] is True


def test_substitution_expands_the_sap_taken_set():
    """SAP-template majors get the same treatment as catalog-packed ones, so a
    templated plan stops scheduling the substituted slot too."""
    tx = [_tx("PHIL 103")]
    assert "ETI 302" not in build_taken_set(tx)
    assert "ETI 302" in build_taken_set(tx, {"ETI 302": "PHIL 103"})


def test_no_substitutions_is_a_no_op():
    """The default path must be byte-identical to before the feature existed."""
    rows = [_req("ETI 302"), _req("MATH 140")]
    tx   = [_tx("MATH 140")]
    assert run_audit(rows, tx) == run_audit(rows, tx, {}) == run_audit(rows, tx, None)


# ── Code validation ──────────────────────────────────────────────────────────

def test_valid_codes():
    for code in ("CHE 100", "ESC 120", "PSU 16", "CAS 100A", "AERSP 1", "CMPSC 131"):
        assert is_valid_code(code), code


def test_invalid_codes():
    for code in ("", "CHE", "100", "che 100", "CHE  100", "CHE-100", "A 1 B"):
        assert not is_valid_code(code), code


def test_norm_code_collapses_whitespace_and_case():
    assert norm_code("  che   100 ") == "CHE 100"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
