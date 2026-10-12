"""
Three counting fixes (Oct 2026):

1. Credential total gate: a choose-one counted above the option the catalog
   minimum assumed counts toward PSU's total (Microbiology, Minor: MICRB 421W is
   3 cr against the 2 the minimum assumed, so 421W + 4 cr of 400-level MICRB = 24).
2. Section-letter variants: a lettered course whose bulletin prerequisite is the
   bare course (COMM 450A needs COMM 450) is a follow-on, not a variant.
3. Departmental pools honour their minimum grade, which keeps exclusive counting
   monotone in grades (Organizational Leadership: OLEAD 100 + 220 at D).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_counting_fixes.py -v
  * plain python:  cd backend && python tests/test_counting_fixes.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import credentials_audit
from audit_engine import run_audit


def _tx(code, status="done", grade="A", credits=3):
    return {"course_code": code, "status": status, "grade": grade, "credits_earned": credits}


def _cred(name, tx):
    return credentials_audit.audit_declared_credentials(
        {"credentials": [{"program": name}]}, tx)[0]


def _complete(a):
    return a["missing"] == 0 and a["in_progress"] == 0


# ── 1. Microbiology total gate ───────────────────────────────────────────────

_MICRB_CORE = [_tx("CHEM 110"), _tx("CHEM 112"), _tx("MICRB 201"), _tx("MICRB 202", credits=2),
               _tx("MICRB 251"), _tx("MICRB 410")]


def test_microbiology_complete_at_24_via_421w():
    # MICRB 421W is stored suffix-stripped, as the transcript parser writes it.
    a = _cred("Microbiology, Minor",
              _MICRB_CORE + [_tx("MICRB 421", credits=3), _tx("MICRB 447", credits=4)])
    assert _complete(a), [(g["name"], g["satisfied"]) for g in a["groups"]]
    assert not any(g["name"] == credentials_audit.TOTAL_GROUP for g in a["groups"])


def test_microbiology_incomplete_at_23_via_422():
    a = _cred("Microbiology, Minor",
              _MICRB_CORE + [_tx("MICRB 422", credits=2), _tx("MICRB 447", credits=4)])
    assert not _complete(a)
    total = [g for g in a["groups"] if g["name"] == credentials_audit.TOTAL_GROUP]
    assert total and total[0]["threshold"] == 1


def test_microbiology_complete_at_24_via_422_and_5_credits():
    a = _cred("Microbiology, Minor",
              _MICRB_CORE + [_tx("MICRB 422", credits=2), _tx("MICRB 447", credits=5)])
    assert _complete(a)


def test_microbiology_421w_in_progress_reads_in_progress_not_missing():
    a = _cred("Microbiology, Minor",
              _MICRB_CORE + [_tx("MICRB 421", status="in_progress", grade="", credits=3),
                             _tx("MICRB 447", credits=4)])
    assert a["missing"] == 0


def test_surplus_is_not_reported_for_cheaper_option():
    rows = [{"program_name": "X", "requirement_group": "G", "group_type": "choose_one",
             "course_code": c, "credits": cr, "pair_group_id": 1}
            for c, cr in (("AAA 101", 3), ("AAA 102", None))]
    r = run_audit(rows, [_tx("AAA 102", credits=2)], exclusive=True)
    assert "credits_over_catalog" not in r["groups"][0]
    r = run_audit(rows, [_tx("AAA 101", credits=4)], exclusive=True)
    assert r["groups"][0]["credits_over_catalog"] == 1


# ── 2. Section-letter follow-ons ─────────────────────────────────────────────

def _req(code):
    return {"program_name": "X", "requirement_group": "G", "group_type": "required",
            "course_code": code}


def test_follow_on_course_does_not_satisfy_its_prerequisite():
    r = run_audit([_req("COMM 450")], [_tx("COMM 450A")])
    assert not r["groups"][0]["satisfied"]
    r = run_audit([_req("KINES 77")], [_tx("KINES 77A")])
    assert not r["groups"][0]["satisfied"]


def test_genuine_section_variants_still_match():
    for req, took in (("CAS 100", "CAS 100A"), ("CAS 100", "CAS 100C"),
                      ("ENGL 15", "ENGL 15E"), ("ENGL 15", "ENGL 15S"),
                      ("MATH 140", "MATH 140G"), ("SPAN 100", "SPAN 100A")):
        r = run_audit([_req(req)], [_tx(took)])
        assert r["groups"][0]["satisfied"], (req, took)


def test_follow_on_itself_still_satisfies_its_own_code():
    r = run_audit([_req("COMM 450A")], [_tx("COMM 450A")])
    assert r["groups"][0]["satisfied"]


# ── 3. Departmental pool minimum grade / monotonicity ────────────────────────

def _olead(grade_100):
    a = _cred("Organizational Leadership, Minor",
              [_tx("OLEAD 100", grade=grade_100), _tx("OLEAD 220", grade="D")])
    return {g["name"]: g["satisfied"] for g in a["groups"]}


def test_dept_pool_ignores_grades_below_minimum():
    assert _olead("D")["Supporting Courses and Related Areas"] is False


def test_raising_a_grade_never_unsatisfies_a_requirement():
    low, high = _olead("D"), _olead("A")
    assert all(high[k] for k, v in low.items() if v)


def test_dept_pool_counts_grades_at_minimum():
    a = _cred("Organizational Leadership, Minor",
              [_tx("OLEAD 220", grade="C"), _tx("OLEAD 320", grade="C")])
    sat = {g["name"]: g["satisfied"] for g in a["groups"]}
    assert sat["Supporting Courses and Related Areas"]


# ── 4. Mixed sections carry a pool's remaining credits and wording ───────────

def _mixed_rows():
    return [
        {"program_name": "X", "requirement_group": "Sec", "group_type": "required",
         "course_code": "PSYCH 100", "credits": 3},
        {"program_name": "X", "requirement_group": "Sec", "group_type": "dept_credits",
         "group_threshold": 12, "pool_seq": 2, "course_code": "__DEPT_CREDITS_PSYCH_1__",
         "dept": "PSYCH", "pool_text": "Select 12 credits in PSYCH"},
    ]


def test_mixed_section_sub_group_carries_credits_needed_and_wording():
    tx = [_tx("PSYCH 100"), _tx("PSYCH 200"), _tx("PSYCH 210")]   # 9 of 12
    r = run_audit(_mixed_rows(), tx)
    g = r["groups"][0]
    assert g["group_type"] == "mixed"
    pool = [s for s in g["sub_groups"] if s["sub_type"] == "dept_credits"][0]
    assert pool["credits_needed"] == 3
    assert pool["pool_text"] == "Select 12 credits in PSYCH"


def test_timeline_schedules_only_the_remaining_credits():
    from routers.timeline import _collect_missing
    tx = [_tx("PSYCH 100"), _tx("PSYCH 200"), _tx("PSYCH 210")]   # 9 of 12
    slots = [m for m in _collect_missing(run_audit(_mixed_rows(), tx)) if m.get("is_pool")]
    assert len(slots) == 1 and slots[0]["credits"] == 3
    assert slots[0]["course_title"] == "Select 12 credits in PSYCH"


def test_mixed_section_without_pool_extras_is_unchanged():
    rows = [_mixed_rows()[0], {"program_name": "X", "requirement_group": "Sec",
            "group_type": "choose_one", "course_code": "STAT 200", "pair_group_id": 1}]
    sub = run_audit(rows, [_tx("PSYCH 100")])["groups"][0]["sub_groups"]
    assert not any(k in s for s in sub for k in ("pool_text", "needs_confirmation",
                                                  "credits_needed"))


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
           if n.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} passed")
