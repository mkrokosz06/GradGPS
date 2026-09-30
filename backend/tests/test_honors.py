"""
Tests for honors (Schreyer) course handling.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_honors.py -v
  * plain python:  cd backend && python tests/test_honors.py

Hermetic — parser helpers, audit engine and SAP matcher, no DynamoDB.

The case behind it: a Schreyer Scholar (Jack, Mechanical Engineering) took the
honors first-year sequence ENGL 137H + CAS 138T, which PSU says "replace both
ENGL 030 and CAS 100" (and 138T is the First-Year Seminar). GradGPS told him he
still owed ENGL 15 and CAS 100 and pushed his graduation a semester.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_engine import run_audit, run_gen_ed_audit
from sap_schedule import build_taken_set, is_taken, match_template
from transcript_parser import _normalise_code, _make_entry, is_honors_code


def _req(code, group="Core", gtype="required", **extra):
    return {
        "program_name": "X", "requirement_group": group,
        "group_type": gtype, "course_code": code, "credits": 3, **extra,
    }


def _tx(code, status="done", grade="A", credits=3, **extra):
    return {"course_code": _normalise_code(code), "status": status, "grade": grade,
            "credits_earned": credits, **extra}


def _status(result, code):
    for g in result["groups"]:
        for src in (g.get("sub_groups") or [g]):
            for item in src["items"]:
                if item["course_code"] == code:
                    return item["status"]
    return None


def _group(result, name):
    return next(g for g in result["groups"] if g["name"] == name)


RCL = [_tx("ENGL 137H"), _tx("CAS 138T")]


# ── Parser ───────────────────────────────────────────────────────────────────

def test_parser_keeps_the_registered_code_and_flags_honors():
    e = _make_entry("BIOL", "230M", 4, 4, "A", "FA 2025", "Hnr Biol Molecules")
    assert e["course_code"] == "BIOL 230"          # M stripped like W
    assert e["raw_code"] == "BIOL 230M"
    assert e["is_writing"] is True and e["is_honors"] is True

    e = _make_entry("CAS", "138T", 3, 3, "A", "SP 2025", "Rcl II")
    assert e["course_code"] == "CAS 138T" and e["is_honors"] is True

    e = _make_entry("IST", "440W", 3, 3, "A", "SP 2025", "")
    assert e["is_honors"] is False


def test_is_honors_code():
    for code in ("ENGL 137H", "MATH 140H", "BIOL 230M", "CAS 138T", "GEOG 20U"):
        assert is_honors_code(code), code
    for code in ("ENGL 15", "CAS 100A", "IST 440W", "ENGL XFRGH", "SOC 119N"):
        assert not is_honors_code(code), code


# ── RCL fills ENGL 15 / CAS 100 / the seminar ────────────────────────────────

def test_rcl_satisfies_gen_ed_writing_and_speech():
    rows = [
        _req("ENGL 15", "Communication: Writing", "choose_one", pair_group_id=2),
        _req("ENGL 30", "Communication: Writing", "choose_one", pair_group_id=2),
        _req("CAS 100A", "Communication: Effective Speech", "choose_one", pair_group_id=1, multi_category=True),
        _req("CAS 100B", "Communication: Effective Speech", "choose_one", pair_group_id=1, multi_category=True),
    ]
    before = run_gen_ed_audit(rows, [])
    assert not _group(before, "Communication: Writing")["satisfied"]

    result = run_gen_ed_audit(rows, RCL)
    assert _group(result, "Communication: Writing")["satisfied"]
    assert _group(result, "Communication: Effective Speech")["satisfied"]


def test_rcl_satisfies_the_major_rows_that_name_engl_15_and_cas_100():
    """Jack's ME audit: 'ENGL 15 or ENGL 30H' and 'CAS 100A or CAS 100B'."""
    rows = [
        _req("ENGL 15",  gtype="choose_one", pair_group_id=7),
        _req("ENGL 30H", gtype="choose_one", pair_group_id=7),
        _req("CAS 100A", gtype="choose_one", pair_group_id=8),
        _req("CAS 100B", gtype="choose_one", pair_group_id=8),
    ]
    assert run_audit(rows, RCL)["missing"] == 0


def test_rcl_ii_satisfies_a_first_year_seminar_row():
    assert _status(run_audit([_req("PSU 16")], [_tx("CAS 138T")]), "PSU 16") == "done"
    assert _status(run_audit([_req("CHE 100")], [_tx("ENGL 138T")]), "CHE 100") == "done"


def test_fills_are_one_way():
    """ENGL 15 / PSU 6 must never satisfy a requirement that names RCL."""
    rows = [_req("ENGL 137H"), _req("CAS 138T", group="Other")]
    result = run_audit(rows, [_tx("ENGL 15"), _tx("CAS 100A"), _tx("PSU 6")])
    assert _status(result, "ENGL 137H") == "missing"
    assert _status(result, "CAS 138T") == "missing"


def test_rcl_i_alone_does_not_satisfy_speech():
    rows = [_req("CAS 100A", gtype="choose_one", pair_group_id=1),
            _req("CAS 100B", gtype="choose_one", pair_group_id=1)]
    assert run_audit(rows, [_tx("ENGL 137H")])["missing"] == 1


def test_seminar_fill_never_counts_as_gen_ed_domain_credit():
    """GER 83 is both a First-Year Seminar and a GH/IL course. RCL II fills the
    seminar requirement — it must not also hand out 3 GH credits."""
    rows = [_req("GER 83", "GH: Humanities", "choose_credits", group_threshold=3),
            _req("KINES 123S", "GH: Humanities", "choose_credits", group_threshold=3)]
    result = run_gen_ed_audit(rows, [_tx("CAS 138T")])
    assert not _group(result, "GH: Humanities")["satisfied"]


def test_fills_never_count_in_a_departmental_pool():
    """PHIL 83 is a seminar code 138T fills; a 'credits in PHIL' pool must not
    see CAS 138T as a PHIL course."""
    rows = [_req("__POOL__", "PHIL credits", "dept_credits", group_threshold=3, dept="PHIL")]
    result = run_audit(rows, [_tx("CAS 138T")])
    assert _group(result, "PHIL credits")["credits_earned"] == 0


def test_real_course_wins_over_a_fill():
    """A student who took PSU 16 AND 138T: PSU 16's own grade is what counts."""
    rows = [_req("PSU 16", min_grade="C")]
    result = run_audit(rows, [_tx("PSU 16", grade="D"), _tx("CAS 138T")])
    assert _status(result, "PSU 16") == "missing"


# ── Honors variants of regular requirements ──────────────────────────────────

def test_m_suffix_satisfies_the_w_requirement():
    rows = [_req("BIOL 230W"), _req("MATH 311W", group="Other")]
    result = run_audit(rows, [_tx("BIOL 230M", credits=4), _tx("MATH 311M")])
    assert result["missing"] == 0


def test_row_stored_before_m_was_stripped_still_matches():
    """Prod rows parsed before this fix hold 'BIOL 230M' verbatim."""
    stale = {"course_code": "BIOL 230M", "status": "done", "grade": "A", "credits_earned": 4}
    assert run_audit([_req("BIOL 230W")], [stale])["missing"] == 0


def test_suffixed_cross_listing_now_matches():
    """'CAS 137H'/'ENGL 137H' is scraped suffixed, but the transcript row is
    stored as 'ENGL 137' — the alias used to never fire."""
    assert run_audit([_req("CAS 137H")], [_tx("ENGL 137H")])["missing"] == 0


# ── SAP matcher ──────────────────────────────────────────────────────────────

def _template(*slots):
    return {"program_name": "X", "total_credits": 6,
            "semesters": [{"year": 1, "term_season": "FA", "credits": 6, "slots": list(slots)}]}


def test_sap_slots_accept_rcl():
    taken = build_taken_set(RCL)
    assert is_taken("ENGL 15", taken)
    assert is_taken("CAS 100A", taken)
    assert is_taken("PSU 6", taken)
    assert not is_taken("ENGL 137H", build_taken_set([_tx("ENGL 15")]))


def test_sap_rcl_is_not_also_a_free_elective():
    """137H fills the ENGL 15 slot; it must not ALSO be leftover surplus that
    completes a free elective."""
    tpl = _template(
        {"type": "course", "code": "ENGL 15", "credits": 3},
        {"type": "elective", "credits": 3},
    )
    tx = [_tx("ENGL 137H")]
    recs = match_template(tpl, build_taken_set(tx), {}, transcript_courses=tx, used_codes=set())
    assert recs[0]["satisfied"] is True
    assert recs[1]["satisfied"] is False


# ── ENGL 202H ────────────────────────────────────────────────────────────────

def test_engl_202h_covers_the_202_a_through_d_a_major_names():
    rows = [_req("ENGL 202C", gtype="choose_one", pair_group_id=3),
            _req("ENGL 202D", gtype="choose_one", pair_group_id=3)]
    assert run_audit(rows, [_tx("ENGL 202H")])["missing"] == 0
    # one way: a 202C doesn't satisfy a 202H requirement
    assert run_audit([_req("ENGL 202H")], [_tx("ENGL 202C")])["missing"] == 1


def test_engl_202h_counts_once_in_a_pool():
    rows = [_req(c, "GWS", "choose_courses", group_threshold=2)
            for c in ("ENGL 202A", "ENGL 202B", "ENGL 202C", "ENGL 202D", "ENGL 202H")]
    result = run_gen_ed_audit(rows, [_tx("ENGL 202H")])
    assert _group(result, "GWS")["satisfied"] is False   # one course, not five


def test_plan_matches_engl_202h_to_one_slot_only():
    tpl = _template({"type": "course", "code": "ENGL 202C", "credits": 3},
                    {"type": "course", "code": "ENGL 202D", "credits": 3})
    tx = [_tx("ENGL 202H")]
    recs = match_template(tpl, build_taken_set(tx), {}, transcript_courses=tx, used_codes=set())
    assert [r["satisfied"] for r in recs] == [True, False]


# ── Schreyer declaration + thesis rule ───────────────────────────────────────

ME = "Mechanical Engineering, B.S. (Engineering)"
SCHOLAR = {"honors": {"program": "schreyer", "entry": "first_year"}}


def _me_template():
    return {"program_name": ME, "total_credits": 12, "semesters": [
        {"year": 4, "term_season": "FA", "credits": 6, "slots": [
            {"type": "pool", "ref": "major_selection", "label": "Engineering Technical Elective (ETE)", "credits": 3.0},
            {"type": "pool", "ref": "major_selection", "label": "Mechanical Engineering Technical Elective (METE)", "credits": 3.0}]},
        {"year": 4, "term_season": "SP", "credits": 6, "slots": [
            {"type": "pool", "ref": "major_selection", "label": "General Technical Elective (GTE)", "credits": 3.0},
            {"type": "pool", "ref": "major_selection", "label": "Engineering Technical Elective (ETE)", "credits": 3.0}]},
    ]}


def test_me_thesis_replaces_one_ete_and_the_gte_for_a_scholar():
    from honors import apply_thesis_rule
    tpl = _me_template()
    out = apply_thesis_rule(tpl, SCHOLAR)
    codes = [s.get("code") or s.get("label") for sem in out["semesters"] for s in sem["slots"]]
    assert codes == ["ME 494H", "Mechanical Engineering Technical Elective (METE)",
                     "ME 493", "Engineering Technical Elective (ETE)"]
    total = lambda t: sum(s["credits"] for sem in t["semesters"] for s in sem["slots"])
    assert total(out) == total(tpl) == 12
    # the shared template object is never mutated
    assert tpl["semesters"][0]["slots"][0]["label"] == "Engineering Technical Elective (ETE)"


def test_thesis_rule_is_a_no_op_without_the_declaration_or_a_rule():
    from honors import apply_thesis_rule
    tpl = _me_template()
    assert apply_thesis_rule(tpl, {}) is tpl
    assert apply_thesis_rule(tpl, {"honors": {"program": "other"}}) is tpl
    other = {**tpl, "program_name": "Accounting, B.S. (Business)"}
    assert apply_thesis_rule(other, SCHOLAR) is other


def test_in_progress_thesis_fills_the_swapped_slot():
    """Jack: ME 494H in progress (stored 'ME 494') satisfies the thesis slot."""
    from honors import apply_thesis_rule
    tpl = apply_thesis_rule(_me_template(), SCHOLAR)
    tx = [_tx("ME 494H", status="in_progress")]
    recs = match_template(tpl, build_taken_set(tx), {}, transcript_courses=tx, used_codes=set())
    assert recs[0]["satisfied"] is True


class _FakeUsers:
    def __init__(self, item):
        self.item = item

    def get_item(self, Key):
        return {"Item": self.item} if self.item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None):
        if UpdateExpression.startswith("REMOVE"):
            self.item.pop(UpdateExpression.split()[1], None)
        else:
            self.item["honors"] = ExpressionAttributeValues[":h"]


def test_set_honors_endpoint():
    from fastapi import HTTPException
    from routers import users
    real = users.users_table
    users.users_table = fake = _FakeUsers({"user_id": "u1", "major": ME})
    try:
        out = users.set_my_honors(users.HonorsBody(program="schreyer", entry="second_year"), "u1")
        assert out["honors"] == fake.item["honors"] == {"program": "schreyer", "entry": "second_year"}
        assert users.set_my_honors(users.HonorsBody(program="schreyer"), "u1")["honors"]["entry"] == "first_year"
        for bad in (users.HonorsBody(program="paterno"), users.HonorsBody(program="schreyer", entry="x")):
            try:
                users.set_my_honors(bad, "u1")
                assert False, "should refuse"
            except HTTPException as e:
                assert e.status_code == 400
        assert users.set_my_honors(users.HonorsBody(program=None), "u1")["honors"] is None
        assert "honors" not in fake.item
    finally:
        users.users_table = real


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
           if n.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} passed")
