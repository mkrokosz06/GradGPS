"""
Tests for plan-grid placeholder slots.

A codeless grid cell the scraper didn't recognise ("400-Level HIST Course",
"Option Course", "Application Focus Selection", "Chemical Engineering Elective")
used to become a category-less gen-ed slot, and those are retired once a
student's gen-eds are done — so major coursework silently left the plan of
every student far enough along (1,137 slots in 187 templates). These hold down:

  * only genuine gen-ed labels stay gen-ed; B.A. requirements and major
    requirements get their own slot kinds
  * only an unqualified elective is free
  * a major placeholder is satisfied by a course the major audit credited to a
    pool the plan doesn't itemize — never by leftover electives, never by a
    course that belongs to a named slot's pool
  * Smeal's business breadth keeps its two plain sequence slots

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_plan_placeholders.py -v
  * plain python:  cd backend && python tests/test_plan_placeholders.py

Hermetic — no DynamoDB, no network.
"""

import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from sap_schedule import build_major_pool_codes, match_template, slot_identity
from scrape_sap import _classify, _normalize_breadth


def _kind(label, credits=3.0):
    s = _classify(label, [], credits)
    return s["type"] if s["type"] != "pool" else s["ref"]


# ── Classifying a codeless cell ──────────────────────────────────────────────

def test_major_cells_are_major_slots_not_gen_eds():
    for label in ["400-Level HIST Course", "Option Course", "Concentration Selection",
                  "MATSE Specialization Course 1 from Department List", "Literature Selection"]:
        assert _kind(label) == "major_selection", label
    assert _kind("Application Focus Selection") == "application_focus"


def test_gen_ed_and_ba_cells_keep_their_meaning():
    for label in ["General Education Course (GHW)", "First-Year Seminar", "US Cultures",
                  "General Education Selection", "Health and Physical Activity"]:
        assert _kind(label) == "gen_ed", label
    for label in ["BA Fields", "BA World Cultures Course", "World Cultures", "Foreign Language (Level 1)"]:
        assert _kind(label) == "ba_requirement", label


def test_zero_credit_instruction_cell_stays_inert():
    assert _kind("Enter the major before the end of this semester", 0) == "gen_ed"


def test_only_an_unqualified_elective_is_free():
    for label in ["Elective", "General Elective Course", "Free Elective", "Elective (US)", "Minor/Elective"]:
        assert _kind(label) == "elective", label
    for label in ["Chemical Engineering Elective", "Technical Elective (400-level)",
                  "CMPEN Elective", "Professional Elective"]:
        assert _kind(label) == "major_selection", label


def test_placeholder_carries_the_dept_and_level_it_names():
    s = _classify("400-Level HIST Course", [], 3.0)
    assert (s["dept"], s["level"]) == ("HIST", 400)
    assert "dept" not in _classify("HIST/GEOG Option", [], 3.0)       # ambiguous: no dept
    kind, key = slot_identity(s, 12)
    assert key == "pool:MAJOR_SELECTION:HIST:400#s12"


def test_supporting_and_breadth_cells_keep_their_anchor_course():
    s = _classify("PHYS 213 (or Supporting Course)", ["PHYS 213"], 2.0)
    assert s["ref"] == "supporting" and s["codes"] == ["PHYS 213"]
    s = _classify("BA 411 (or Business Breadth Course)", ["BA 411"], 3.0)
    assert s["ref"] == "business_breadth" and s["codes"] == ["BA 411"]


def test_business_breadth_keeps_two_plain_sequence_slots():
    sems = [{"slots": [{"type": "pool", "ref": "business_breadth", "codes": ["BA 411"], "label": "x"},
                       {"type": "pool", "ref": "business_breadth", "codes": ["BA 411"], "label": "x"},
                       {"type": "pool", "ref": "business_breadth", "label": "Business Breadth Course"}]}]
    _normalize_breadth(sems)
    assert [bool(s.get("codes")) for s in sems[0]["slots"]] == [False, True, False]


# ── Satisfying a placeholder ─────────────────────────────────────────────────

def _audit(*pools):
    """An audit result with one pool sub-group per (options, taken) pair."""
    subs = [{"sub_type": "choose_credits",
             "items": [{"course_code": c, "status": "done" if c in taken else "missing"}
                       for c in options]} for options, taken in pools]
    return {"groups": [{"group_type": "mixed", "sub_groups": subs, "items": []}]}


TEMPLATE = {"program_name": "Test, B.S.", "semesters": [
    {"term_season": "FA", "year": 1, "slots": [
        {"type": "course", "code": "IST 140", "credits": 3},
        {"type": "pool", "ref": "major_selection", "label": "400-Level HIST Course",
         "dept": "HIST", "level": 400, "credits": 3},
        {"type": "pool", "ref": "application_focus", "label": "Application Focus Selection", "credits": 3},
        {"type": "pool", "ref": "application_focus", "label": "Application Focus Selection", "credits": 3},
        {"type": "elective", "label": "Elective", "credits": 3}]}]}


def _tx(*codes):
    return [{"course_code": c, "status": "done", "grade": "A", "credits_earned": 3} for c in codes]


def _satisfied(tx, audit):
    recs = match_template(TEMPLATE, {c["course_code"] for c in tx}, {}, transcript_courses=tx,
                          used_codes=set(), major_pool_codes=build_major_pool_codes(audit, TEMPLATE))
    return {r["slot"].get("label", r["slot"].get("code")): r["satisfied"] for r in recs}, recs


def test_placeholder_is_satisfied_by_the_majors_own_pool_course():
    audit = _audit((["HIST 401", "HIST 450"], {"HIST 401"}), (["MKTG 301", "BLAW 243"], {"MKTG 301"}))
    tx = _tx("HIST 401", "MKTG 301")
    _, recs = _satisfied(tx, audit)
    matched = [r["matched_code"] for r in recs if r["satisfied"] and r["slot"].get("type") == "pool"]
    assert "HIST 401" in matched and "MKTG 301" in matched


def test_a_course_belonging_to_a_named_slots_pool_does_not_fill_a_placeholder():
    # CMPSC 131 was taken for the intro-programming pool the template shows as IST 140.
    audit = _audit((["CMPSC 131", "IST 140"], {"CMPSC 131"}))
    res, _ = _satisfied(_tx("CMPSC 131"), audit)
    assert res["Application Focus Selection"] is False


def test_leftover_electives_never_fill_a_major_placeholder():
    res, recs = _satisfied(_tx("GEOG 30", "ANTH 45"), _audit())
    assert not any(r["satisfied"] for r in recs if r["slot"].get("ref") in ("major_selection", "application_focus"))
    assert res["Elective"] is True                        # the free elective still takes one


def test_dept_and_level_must_both_match():
    audit = _audit((["HIST 201", "HIST 401"], {"HIST 201"}))
    res, _ = _satisfied(_tx("HIST 201"), audit)
    assert res["400-Level HIST Course"] is False


# ── The shipped templates ────────────────────────────────────────────────────

def test_no_template_keeps_a_major_cell_as_a_generic_gen_ed():
    tdir = os.path.join(BACKEND, "sap_templates")
    eti = json.load(open(os.path.join(tdir, "enterprise-technology-integration-bs-information-sciences-and-technology.json"),
                         encoding="utf-8"))
    refs = [s.get("ref") for sem in eti["semesters"] for s in sem["slots"]]
    codes = [s.get("code") for sem in eti["semesters"] for s in sem["slots"]]
    assert refs.count("application_focus") == 4
    assert "ETI 200" in codes and "ETI 100" in codes                 # PSU's current grid


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc!r}")
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
