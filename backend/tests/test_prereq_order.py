"""
Tests for prerequisite / corequisite ordering on the timeline.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_prereq_order.py -v
  * plain python:  cd backend && python tests/test_prereq_order.py

Hermetic: the requisite data is swapped for a small fixture, so no test depends
on what the bulletin currently says. The parser tests use real bulletin text.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import course_prereqs
from routers.timeline import (
    _pack_ordered,
    _slice_even,
    _enforce_prereq_order,
    _reflow_template,
    _emit_semester,
)


# ── Fixture data ─────────────────────────────────────────────────────────────

_FIXTURE = {
    "BB 200":  {"pre": [["AA 100"]]},
    "CC 300":  {"pre": [["BB 200"]]},
    "DD 400":  {"pre": [["CC 300"]]},
    "XX 300":  {"co": [["YY 300"]]},                    # XX beside (or after) YY
    "KK 1":    {"co": [["KK 2"]]},                      # mutual corequisites
    "KK 2":    {"co": [["KK 1"]]},
    "KK 9":    {"pre": [["KK 1"]]},
    "EBF 200": {"pre": [["ECON 102"]]},
}


_REAL_DATA = course_prereqs._data


def setup_module(_module=None):
    fixture = {course_prereqs.norm(k): v for k, v in _FIXTURE.items()}
    course_prereqs._data = lambda: fixture          # type: ignore[assignment]


def teardown_module(_module=None):
    course_prereqs._data = _REAL_DATA


def _c(code, cr=3):
    return {"course_code": code, "credits": cr}


def _gen(i):
    return {"course_code": "General Education", "credits": 3, "is_pool": True,
            "gen_ed_categories": ["GN"], "slot_key": f"gened:{i}"}


def _where(chunks):
    return {c["course_code"]: i for i, ch in enumerate(chunks) for c in ch}


# ── Parser (real bulletin wording) ───────────────────────────────────────────

def test_parse_glued_concurrent_heading():
    # ARCH 203: prerequisites and corequisites share one <p>.
    got = course_prereqs.parse([
        "Enforced Prerequisite at Enrollment: C or better in ARCH\xa0132 and AE\xa0210 "
        "Enforced Concurrent at Enrollment: ARCH\xa0231 and AE\xa0421"])
    assert got == {"pre": [["ARCH 132"], ["AE 210"]], "co": [["ARCH 231"], ["AE 421"]]}


def test_parse_grouped_alternatives_and_flattened_branch():
    got = course_prereqs.parse([
        "Enforced Prerequisite at Enrollment: ( ECON\xa0102 or ECON\xa0104 ) and "
        "ACCTG\xa0211 or ( ACCTG\xa0201 and ACCTG\xa0202 )"])
    assert got["pre"] == [["ECON 102", "ECON 104"], ["ACCTG 211", "ACCTG 201", "ACCTG 202"]]


def test_parse_dangling_or_joins_concurrent_segment():
    # MATH 414: "MATH 230 or Concurrent: MATH 232 ..." is ONE disjunction.
    got = course_prereqs.parse([
        "Enforced Prerequisite at Enrollment: MATH\xa0230 or Concurrent: MATH\xa0232 or "
        "( MATH\xa0231 and RM\xa0214 )"])
    assert "pre" not in got
    assert got["co"] == [["MATH 230", "MATH 232", "MATH 231", "RM 214"]]


def test_parse_drops_escape_hatches_and_recommendations():
    got = course_prereqs.parse([
        "Enforced Prerequisite at Enrollment: MATH\xa021 or satisfactory performance on "
        "the mathematics placement examination.",
        "Prerequisites: 7th Semester standing; COREQUISITE: CI\xa0495D ; "
        "Recommended Preparation: Official clearances required."])
    assert got == {"co": [["CI 495D"]]}


def test_parse_comma_list_without_or_is_all_required():
    got = course_prereqs.parse([
        "Prerequisite: A grade of C or better in SPLED395W , SPLED401 , SPLED\xa0418"])
    assert got["pre"] == [["SPLED 395"], ["SPLED 401"], ["SPLED 418"]]


def test_norm_strips_attribute_suffix_keeps_section():
    assert course_prereqs.norm("MATH 140H") == "MATH 140"
    assert course_prereqs.norm("ETI 300W") == "ETI 300"
    assert course_prereqs.norm("CAS 100A") == "CAS 100A"


# ── _pack_ordered ────────────────────────────────────────────────────────────

def test_no_requisites_is_slice_even():
    items = [_c(f"ZZ {i}") for i in range(10)] + [_gen(i) for i in range(4)]
    assert _pack_ordered(items, 4) == _slice_even(items, 4)


def test_prerequisite_never_shares_a_term():
    # Even slicing would put AA 100 and BB 200 together.
    items = [_c("AA 100"), _c("BB 200"), _gen(1), _gen(2)]
    w = _where(_pack_ordered(items, 2))
    assert w["BB 200"] > w["AA 100"]


def test_done_prerequisite_imposes_nothing():
    items = [_c("AA 100"), _c("BB 200")]
    assert _pack_ordered(items, 1, done={"AA 100"}) == _slice_even(items, 1)


def test_corequisite_listed_later_pulls_course_to_it():
    # XX 300 sliced into term 0, its corequisite YY 300 into term 1.
    items = [_c("XX 300"), _gen(1), _c("YY 300"), _gen(2)]
    w = _where(_pack_ordered(items, 2))
    assert w["XX 300"] >= w["YY 300"]


def test_mutual_corequisites_stay_together_and_follower_after():
    items = [_c("KK 1"), _gen(1), _gen(2), _c("KK 2"), _gen(3), _c("KK 9"), _gen(4), _gen(5)]
    w = _where(_pack_ordered(items, 4))
    assert w["KK 1"] == w["KK 2"]
    assert w["KK 9"] > w["KK 1"]


def test_chain_starts_early_enough_to_finish_on_time():
    # A 4-course chain over 4 terms must start in the first — even though even
    # slicing parks the whole chain in the back half behind gen-eds.
    items = [_gen(i) for i in range(8)] + [_c("AA 100"), _c("BB 200"), _c("CC 300"), _c("DD 400")]
    chunks = [c for c in _pack_ordered(items, 4) if c]
    w = _where(chunks)
    assert [w["AA 100"], w["BB 200"], w["CC 300"], w["DD 400"]] == [0, 1, 2, 3]
    assert len(chunks) == 4


def test_template_same_semester_pair_is_allowed():
    # PSU's plan puts EBF 200 beside ECON 102; that pairing is honoured.
    tsem = {"ECON 102": 3, "EBF 200": 3}
    items = [_c("ECON 102"), _c("EBF 200")]
    w = _where(_pack_ordered(items, 1, tsem=tsem))
    assert w["EBF 200"] == w["ECON 102"]


# ── _enforce_prereq_order (final pass on the emitted plan) ───────────────────

def test_enforce_moves_course_after_its_prerequisite_and_swaps_filler():
    future = [
        _emit_semester("FA 2026", [_c("BB 200"), _c("AA 100"), _gen(1), _gen(2), _gen(3)]),
        _emit_semester("SP 2027", [_gen(4), _gen(5), _gen(6), _gen(7), _gen(8)]),
    ]
    out = _enforce_prereq_order(future, set())
    codes = [[c["course_code"] for c in s["courses"]] for s in out]
    assert "BB 200" in codes[1] and "AA 100" in codes[0]
    assert out[1]["courses"][-1]["moved_for_prerequisite"] is True
    assert [s["credits"] for s in out] == [15.0, 15.0]     # filler swapped back


def test_enforce_leaves_pinned_course_alone():
    future = [_emit_semester("FA 2026", [_c("AA 100"), _c("BB 200")])]
    future[0]["courses"][1]["pinned"] = True
    out = _enforce_prereq_order(future, set())
    assert len(out) == 1 and len(out[0]["courses"]) == 2


def test_enforce_adds_a_term_when_the_chain_needs_one():
    future = [_emit_semester("FA 2026", [_c("AA 100"), _c("BB 200")])]
    out = _enforce_prereq_order(future, set())
    assert [s["term"] for s in out] == ["FA 2026", "SP 2027"]


# ── SAP rebalance ────────────────────────────────────────────────────────────

def _rec(code, sem, satisfied=False, season="FA"):
    return {"item": _c(code), "satisfied": satisfied, "sem_index": sem, "season": season}


def test_rebalance_keeps_prerequisite_order():
    # One satisfied slot sends the plan through the rebalance, which used to
    # slice the flattened template straight across semester boundaries.
    recs = [_rec("QQ 1", 0, satisfied=True),
            _rec("AA 100", 1), _rec("GG 1", 1), _rec("BB 200", 2), _rec("GG 2", 2),
            _rec("CC 300", 3), _rec("GG 3", 3)]
    out = _reflow_template(recs, "SP 2026", done=set())
    w = {c["course_code"]: i for i, s in enumerate(out) for c in s["courses"]}
    assert w["AA 100"] < w["BB 200"] < w["CC 300"]


if __name__ == "__main__":
    setup_module()
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
