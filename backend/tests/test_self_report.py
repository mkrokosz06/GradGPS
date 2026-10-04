"""
Tests for no-transcript mode (self_report.py + the grade semantics it relies on).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_self_report.py -v
  * plain python:  cd backend && python tests/test_self_report.py

Hermetic: no DynamoDB.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import self_report
from audit_engine import run_audit
from plan_templates import load_template

BULLETIN = {"IST 140": {"title": "Intro to Programming", "credits": 3.0},
            "MATH 110": {"title": "Techniques of Calculus", "credits": 4.0},
            "MATH 140": {"title": "Calculus I", "credits": 4.0}}


def test_current_term():
    assert self_report.current_term(date(2026, 10, 4)) == "FA 2026"
    assert self_report.current_term(date(2027, 2, 1)) == "SP 2027"
    assert self_report.current_term(date(2026, 7, 1)) == "FA 2026"   # summer -> coming fall


def test_previous_terms_skip_summer():
    assert self_report.previous_terms("FA 2026", 3) == ["SP 2025", "FA 2025", "SP 2026"]
    assert self_report.previous_terms("SP 2027", 2) == ["SP 2026", "FA 2026"]
    assert self_report.previous_terms("FA 2026", 0) == []


def test_plan_semesters_from_template():
    tpl = {"semesters": [
        {"year": 1, "term_season": "FA", "slots": [
            {"type": "course", "code": "IST 140", "credits": 3},
            {"type": "choose_one", "codes": ["MATH 110", "MATH 140"], "credits": 4},
            {"type": "gen_ed", "category": "GH", "credits": 3},
        ]},
        {"year": 1, "term_season": "SU", "slots": [
            {"type": "course", "code": "IST 495", "credits": 3}]},
        {"year": 1, "term_season": "SP", "slots": [
            {"type": "pool", "ref": "dept_level", "dept": "IST", "label": "IST 400-Level", "credits": 3},
            {"type": "elective", "label": "Elective", "credits": 2}]},
    ]}
    sems = self_report.plan_semesters(tpl, BULLETIN)
    assert [s["season"] for s in sems] == ["FA", "SP"]           # summer left out
    a, b, c = sems[0]["items"]
    assert a == {"kind": "course", "code": "IST 140", "title": "Intro to Programming", "credits": 3.0}
    assert b["kind"] == "choice" and [o["code"] for o in b["options"]] == ["MATH 110", "MATH 140"]
    assert c["kind"] == "open" and c["gen_ed"] == "GH"
    assert sems[1]["items"][0]["dept"] == "IST"
    assert sems[1]["items"][1]["credits"] == 2.0


def test_real_template_loads():
    tpl = load_template("Enterprise Technology Integration, B.S. (Information Sciences and Technology)")
    sems = self_report.plan_semesters(tpl, BULLETIN)
    assert len(sems) == 8
    assert sems[0]["items"][0]["code"] == "IST 140"


def test_suggestions_named_requirements_only():
    rows = [{"course_code": "IST 140", "group_type": "required"},
            {"course_code": "MATH 110", "group_type": "choose_one"},
            {"course_code": "MATH 140", "group_type": "choose_credits"},   # pool: skipped
            {"course_code": "IST 140", "group_type": "required"},          # dup
            {"course_code": "FAKE 999", "group_type": "required"}]         # not in bulletin
    assert [s["code"] for s in self_report.suggestions_from_rows(rows, BULLETIN)] == ["IST 140", "MATH 110"]


def _status(result, code):
    for g in result["groups"]:
        for src in (g.get("sub_groups") or [g]):
            for item in src["items"]:
                if item["course_code"] == code:
                    return item["status"]


def test_grade_semantics():
    """No grade (C or better) meets a C minimum; the below-C marker doesn't."""
    rows = [{"program_name": "X", "requirement_group": "Core", "group_type": "required",
             "course_code": "IST 140", "credits": 3, "min_grade": "C"}]
    ok = run_audit(rows, [{"course_code": "IST 140", "status": "done", "grade": "", "credits_earned": 3}])
    assert _status(ok, "IST 140") == "done"
    low = run_audit(rows, [{"course_code": "IST 140", "status": "done",
                            "grade": self_report.BELOW_C_GRADE, "credits_earned": 3}])
    assert _status(low, "IST 140") != "done"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
