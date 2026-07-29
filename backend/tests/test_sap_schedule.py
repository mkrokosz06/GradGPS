"""
Tests for the SAP match stage (sap_schedule.match_template).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_sap_schedule.py -v
  * plain python:  cd backend && python tests/test_sap_schedule.py

Hermetic — uses the real hand-encoded Accounting template file but no DynamoDB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plan_templates import load_template
from sap_schedule import (
    _base,
    _codes_match,
    build_taken_set,
    build_gen_ed_satisfied,
    build_used_codes,
    is_taken,
    match_template,
    slot_to_item,
)

ACCTG = "Accounting, B.S. (Business)"


# ── code normalization / matching ────────────────────────────────────────────

def test_base_strips_attribute_suffix_only():
    assert _base("ACCTG 403W") == "ACCTG 403"
    assert _base("ENGL 202H") == "ENGL 202"
    assert _base("CAS 100A") == "CAS 100A"   # section letter preserved


def test_codes_match_section_letter():
    assert _codes_match("CAS 100", "CAS 100A")
    assert _codes_match("ACCTG 403W", "ACCTG 403")
    assert not _codes_match("MATH 14", "MATH 140")   # not a section-letter case
    assert not _codes_match("ACCTG 211", "ACCTG 311")


def test_equivalence_matching():
    # IST 301 was renamed ETI 301 — a student who took IST 301 satisfies ETI 301.
    taken = build_taken_set([{"course_code": "IST 301", "status": "done"}])
    assert is_taken("ETI 301", taken)


def test_transfer_and_missing_not_taken():
    taken = build_taken_set([
        {"course_code": "ACCTG 211", "status": "done"},
        {"course_code": "FIN 301", "status": "in_progress"},
        {"course_code": "MKTG 301", "status": "missing"},   # not taken
    ])
    assert is_taken("ACCTG 211", taken)
    assert is_taken("FIN 301", taken)
    assert not is_taken("MKTG 301", taken)


# ── match_template: no transcript ────────────────────────────────────────────

def test_no_transcript_nothing_satisfied():
    tpl = load_template(ACCTG)
    recs = match_template(tpl, taken=set(), gen_ed_satisfied={})
    assert len(recs) == sum(len(s["slots"]) for s in tpl["semesters"])
    assert all(not r["satisfied"] for r in recs)
    assert all(r["item"] is not None for r in recs)
    # Order preserved: first record is the first slot of semester 0.
    assert recs[0]["sem_index"] == 0
    assert recs[0]["item"]["course_code"] == "PSU 6"


def test_no_transcript_total_credits_120():
    tpl = load_template(ACCTG)
    recs = match_template(tpl, taken=set())
    total = sum(float(r["item"]["credits"]) for r in recs)
    assert abs(total - 120) < 0.01


# ── match_template: with a partial transcript ────────────────────────────────

def test_taken_courses_are_satisfied_and_dropped():
    tpl = load_template(ACCTG)
    taken = build_taken_set([
        {"course_code": "ACCTG 211", "status": "done"},
        {"course_code": "ECON 102", "status": "done"},
        {"course_code": "MGMT 301", "status": "done"},
        {"course_code": "MATH 140", "status": "done"},   # satisfies a GQ choose_one
    ])
    recs = match_template(tpl, taken, gen_ed_satisfied={})
    satisfied_codes = {r["matched_code"] for r in recs if r["satisfied"]}
    assert "ACCTG 211" in satisfied_codes
    assert "ECON 102" in satisfied_codes
    assert "MGMT 301" in satisfied_codes
    assert "MATH 140" in satisfied_codes
    # Satisfied slots carry no schedulable item.
    assert all(r["item"] is None for r in recs if r["satisfied"])
    # A course not taken is still scheduled.
    assert any(r["item"] and r["item"]["course_code"] == "MKTG 301" for r in recs)


def test_consumption_one_course_satisfies_one_slot():
    # BLAW 341 / BA 342 appears as a choose_one in BOTH Year 3 semesters (take
    # both). Taking only BA 342 must satisfy exactly ONE of the two slots.
    tpl = load_template(ACCTG)
    taken = build_taken_set([{"course_code": "BA 342", "status": "done"}])
    recs = match_template(tpl, taken)
    pair_slots = [r for r in recs
                  if r["slot"].get("type") == "choose_one"
                  and set(r["slot"].get("codes", [])) == {"BLAW 341", "BA 342"}]
    assert len(pair_slots) == 2
    assert sum(1 for r in pair_slots if r["satisfied"]) == 1


def test_gen_ed_category_satisfaction():
    tpl = load_template(ACCTG)
    recs = match_template(tpl, taken=set(), gen_ed_satisfied={"US": True})
    us_slots = [r for r in recs if r["slot"].get("category") == "US"]
    assert us_slots and all(r["satisfied"] for r in us_slots)
    # A different category isn't affected.
    il_slots = [r for r in recs if r["slot"].get("category") == "IL"]
    assert il_slots and all(not r["satisfied"] for r in il_slots)


# ── match_template: un-anchored pools & free electives ───────────────────────

def _wl_tpl():
    """Two world-language slots + one free elective + one required course."""
    return {"semesters": [{"year": 1, "term_season": "FA", "slots": [
        {"type": "course", "code": "ACCTG 211", "credits": 4},
        {"type": "pool", "ref": "world_language", "label": "World Language - Level One", "credits": 4},
        {"type": "pool", "ref": "world_language", "label": "World Language - Level Two", "credits": 4},
        {"type": "elective", "label": "Elective", "credits": 3},
    ]}]}


def test_world_language_satisfied_from_leftover_language_courses():
    courses = [{"course_code": "SPAN 1", "status": "done", "credits_earned": 4},
               {"course_code": "SPAN 2", "status": "done", "credits_earned": 4}]
    recs = match_template(_wl_tpl(), build_taken_set(courses),
                          transcript_courses=courses)
    wl = [r for r in recs if r["slot"].get("ref") == "world_language"]
    assert [r["satisfied"] for r in wl] == [True, True]
    assert {r["matched_code"] for r in wl} == {"SPAN 1", "SPAN 2"}
    # Language courses were claimed by the WL slots — none left for the elective.
    elec = next(r for r in recs if r["slot"]["type"] == "elective")
    assert not elec["satisfied"]


def test_world_language_uses_single_majority_dept():
    # One GER course + one SPAN course: only the majority dept's sequence counts,
    # so exactly one WL slot is satisfied (SPAN 1 + SPAN 2 beat GER 1).
    courses = [{"course_code": "SPAN 1", "status": "done", "credits_earned": 4},
               {"course_code": "SPAN 2", "status": "done", "credits_earned": 4},
               {"course_code": "GER 1", "status": "done", "credits_earned": 4}]
    recs = match_template(_wl_tpl(), build_taken_set(courses),
                          transcript_courses=courses)
    wl = [r for r in recs if r["slot"].get("ref") == "world_language"]
    assert {r["matched_code"] for r in wl if r["satisfied"]} == {"SPAN 1", "SPAN 2"}
    # The stray GER course becomes surplus and covers the 3-cr elective.
    elec = next(r for r in recs if r["slot"]["type"] == "elective")
    assert elec["satisfied"]


def _dept_level_tpl():
    """Two PLSC 400-level selection slots + one free elective."""
    return {"semesters": [{"year": 4, "term_season": "FA", "slots": [
        {"type": "pool", "ref": "dept_level", "dept": "PLSC", "level": 400,
         "label": "PLSC 400-Level Course", "credits": 3},
        {"type": "pool", "ref": "dept_level", "dept": "PLSC", "level": 400,
         "label": "PLSC 400-Level Course", "credits": 3},
        {"type": "elective", "label": "Elective", "credits": 3},
    ]}]}


def test_dept_level_satisfied_from_leftover_dept_courses():
    # One 400-level PLSC course fills ONE slot; the 100-level course doesn't
    # match the level, so it falls through to the elective surplus pool.
    courses = [{"course_code": "PLSC 412", "status": "done", "credits_earned": 3},
               {"course_code": "PLSC 14", "status": "done", "credits_earned": 3}]
    recs = match_template(_dept_level_tpl(), build_taken_set(courses),
                          transcript_courses=courses)
    dl = [r for r in recs if r["slot"].get("ref") == "dept_level"]
    assert [r["satisfied"] for r in dl] == [True, False]
    assert dl[0]["matched_code"] == "PLSC 412"
    elec = next(r for r in recs if r["slot"]["type"] == "elective")
    assert elec["satisfied"]   # PLSC 14 credits became surplus


def test_dept_level_item_title_names_dept_and_level():
    item = slot_to_item({"type": "pool", "ref": "dept_level", "dept": "PLSC",
                         "level": 400, "label": "PLSC 400-Level Course", "credits": 3})
    assert item["is_pool"] and item["course_title"] == "Choose a 400-level PLSC course"
    assert item["course_code"] == "PLSC 400-Level Course"


def test_electives_satisfied_by_surplus_not_by_used_courses():
    # PHIL 103 was consumed by the gen-ed audit (used_codes) → not surplus;
    # KINES 61 (1cr) is surplus but under the 3-cr slot → stays scheduled.
    courses = [{"course_code": "ACCTG 211", "status": "done", "credits_earned": 4},
               {"course_code": "PHIL 103", "status": "done", "credits_earned": 3},
               {"course_code": "KINES 61", "status": "done", "credits_earned": 1}]
    recs = match_template(_wl_tpl(), build_taken_set(courses),
                          transcript_courses=courses,
                          used_codes={"PHIL 103"})
    elec = next(r for r in recs if r["slot"]["type"] == "elective")
    assert not elec["satisfied"]
    # Without the used_codes exclusion the 3-cr PHIL course would cover it.
    recs = match_template(_wl_tpl(), build_taken_set(courses),
                          transcript_courses=courses)
    elec = next(r for r in recs if r["slot"]["type"] == "elective")
    assert elec["satisfied"] and elec["matched_code"] == "3 surplus credits"


def test_no_transcript_courses_param_keeps_old_behavior():
    courses = [{"course_code": "SPAN 1", "status": "done", "credits_earned": 4}]
    recs = match_template(_wl_tpl(), build_taken_set(courses))
    assert all(not r["satisfied"] for r in recs
               if r["slot"].get("ref") == "world_language" or r["slot"]["type"] == "elective")


def test_build_used_codes_collects_done_and_in_progress():
    audit = {"groups": [{"items": [
        {"course_code": "PHIL 103", "status": "done"},
        {"course_code": "ART 20", "status": "in_progress"},
        {"course_code": "MUSIC 5", "status": "missing"},
    ]}]}
    assert build_used_codes(audit, None) == {"PHIL 103", "ART 20"}


# ── slot_to_item shaping ─────────────────────────────────────────────────────

def test_slot_to_item_shapes():
    assert slot_to_item({"type": "course", "code": "ACCTG 211", "credits": 4}) == {
        "course_code": "ACCTG 211", "course_title": "", "credits": 4.0}

    ge = slot_to_item({"type": "gen_ed", "category": "GN", "credits": 3})
    assert ge["is_pool"] and ge["gen_ed_categories"] == ["GN"]

    pool = slot_to_item({"type": "pool", "label": "World Language", "credits": 4, "ref": "world_language"})
    assert pool["is_pool"] and pool["pool_needed_credits"] == 4 and pool["pool_ref"] == "world_language"

    choose = slot_to_item({"type": "choose_one", "codes": ["BLAW 341", "BA 342"], "credits": 3})
    assert " or " in choose["course_code"]


def test_choose_one_label_drops_crosslisted_twin():
    # ENGL 137H / CAS 137H are one cross-listed course — show it once. The full
    # code list still drives matching, so a CAS 137H transcript satisfies the slot.
    item = slot_to_item({"type": "choose_one", "credits": 3,
                         "codes": ["ENGL 15", "ENGL 30H", "ESL 15", "ENGL 137H", "CAS 137H"]})
    assert item["course_code"] == "ENGL 15 or ENGL 30H or ESL 15 or ENGL 137H"


def test_choose_one_label_keeps_coincidental_number_matches():
    # Non-adjacent same-number codes (and same-dept section variants) are
    # different courses — never collapsed.
    item = slot_to_item({"type": "choose_one", "credits": 3,
                         "codes": ["AGECO 122", "EGEE 101", "METEO 122"]})
    assert item["course_code"] == "AGECO 122 or EGEE 101 or METEO 122"
    item = slot_to_item({"type": "choose_one", "credits": 3,
                         "codes": ["CAS 100A", "CAS 100B", "CAS 100C"]})
    assert item["course_code"] == "CAS 100A or CAS 100B or CAS 100C"


def test_build_gen_ed_satisfied_maps_category_tokens():
    result = {"groups": [
        {"name": "US: United States Cultures", "satisfied": True},
        {"name": "GN: Natural Sciences", "satisfied": False},
    ]}
    m = build_gen_ed_satisfied(result)
    assert m["US"] is True and m["GN"] is False


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
