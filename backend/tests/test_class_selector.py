"""
Tests for the class selector — stable slot identity, course-choice application,
and the _apply_pins semester-pinning post-pass (including its conflict rules).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_class_selector.py -v
  * plain python:  cd backend && python tests/test_class_selector.py

All tests are hermetic — no DynamoDB, no S3, no network. They exercise the pure
helpers in routers/timeline.py and sap_schedule.py directly.
"""

import os
import sys

# Make the backend package importable when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.timeline import (
    _collect_missing,
    _emit_semester,
    _apply_pins,
    _semester_credits,
    _MAX_CREDITS,
)
from sap_schedule import slot_identity, slot_options


# ── slot_identity / slot_options ─────────────────────────────────────────────

def test_slot_identity_is_code_based_and_stable():
    assert slot_identity({"type": "course", "code": "CHEM 110"}, 3) == ("course", "course:CHEM 110")
    # choose_one sorts base codes so order in the template can't change the key
    kind, key = slot_identity({"type": "choose_one", "codes": ["MATH 140", "MATH 110"]}, 5)
    assert kind == "choose_one"
    assert key == "one:MATH 110|MATH 140"
    # attribute suffix is stripped to the base code
    _, key_w = slot_identity({"type": "course", "code": "ENGL 202W"}, 0)
    assert key_w == "course:ENGL 202"


def test_slot_identity_generic_slots_include_sem_index():
    # two category-less gen-ed cells must not collapse to one key
    _, k0 = slot_identity({"type": "gen_ed"}, 0)
    _, k1 = slot_identity({"type": "gen_ed"}, 1)
    assert k0 != k1
    _, e0 = slot_identity({"type": "elective"}, 2)
    assert e0 == "elective:s2"
    # a named gen-ed category keys on the category, not the index
    assert slot_identity({"type": "gen_ed", "category": "US"}, 9) == ("gen_ed", "gened:US")


def test_slot_options_bounded_only_for_code_bearing_slots():
    opts = slot_options({"type": "choose_one", "codes": ["MATH 110", "MATH 140"], "credits": 4})
    assert [o["course_code"] for o in opts] == ["MATH 110", "MATH 140"]
    assert all(o["credits"] == 4 for o in opts)
    # a whole gen-ed category is unbounded → no swap list in v1
    assert slot_options({"type": "gen_ed", "category": "GN"}) == []


# ── _collect_missing slot metadata + course choice ───────────────────────────

def _audit_with_pair():
    return {"groups": [{"name": "Core", "items": [
        {"course_code": "IST 242", "status": "missing", "credits": 3},
        {"course_code": "MATH 110", "status": "missing", "credits": 4,
         "pair_group_id": "p1", "pair_status": "missing"},
        {"course_code": "MATH 140", "status": "missing", "credits": 4,
         "pair_group_id": "p1", "pair_status": "missing"},
    ]}]}


def test_collect_missing_emits_slot_keys():
    out = _collect_missing(_audit_with_pair())
    named = next(c for c in out if c["course_code"] == "IST 242")
    assert named["slot_key"] == "course:IST 242"
    assert named["slot_kind"] == "course"

    pair = next(c for c in out if c.get("slot_kind") == "choose_one")
    assert pair["slot_key"] == "one:MATH 110|MATH 140"
    assert pair["course_code"] == "MATH 110 or MATH 140"
    assert {o["course_code"] for o in pair["options"]} == {"MATH 110", "MATH 140"}
    assert "chosen_code" not in pair


def test_collect_missing_applies_course_choice():
    out = _collect_missing(_audit_with_pair(), {"one:MATH 110|MATH 140": "MATH 140"})
    pair = next(c for c in out if c.get("slot_kind") == "choose_one")
    assert pair["course_code"] == "MATH 140"
    assert pair["chosen_code"] == "MATH 140"


def test_collect_missing_ignores_stale_choice_not_in_pair():
    out = _collect_missing(_audit_with_pair(), {"one:MATH 110|MATH 140": "PHYS 211"})
    pair = next(c for c in out if c.get("slot_kind") == "choose_one")
    assert pair["course_code"] == "MATH 110 or MATH 140"  # unchanged
    assert "chosen_code" not in pair


# ── _apply_pins ──────────────────────────────────────────────────────────────

def _named(code, credits=3):
    return {"course_code": code, "credits": credits,
            "slot_key": f"course:{code}", "slot_kind": "course"}


def test_apply_pins_no_pins_is_passthrough():
    future = [_emit_semester("FA 2026", [_named("IST 242")])]
    assert _apply_pins(future, {}) is future


def test_apply_pins_moves_course_to_pinned_term():
    future = [
        _emit_semester("FA 2026", [_named("IST 242"), _named("ENGL 202C")]),
        _emit_semester("SP 2027", [_named("CHEM 110")]),
    ]
    out = _apply_pins(future, {"course:CHEM 110": "FA 2026"})
    fa = next(s for s in out if s["term"] == "FA 2026")
    chem = next(c for c in fa["courses"] if c["course_code"] == "CHEM 110")
    assert chem["pinned"] is True
    # SP 2027 is now empty and dropped
    assert all(s["term"] != "SP 2027" for s in out)


def test_apply_pins_past_term_moves_to_earliest_with_flag():
    future = [
        _emit_semester("FA 2026", [_named("IST 242")]),
        _emit_semester("SP 2027", [_named("CHEM 110")]),
    ]
    out = _apply_pins(future, {"course:CHEM 110": "SP 2025"})  # already in the past
    fa = next(s for s in out if s["term"] == "FA 2026")
    chem = next(c for c in fa["courses"] if c["course_code"] == "CHEM 110")
    assert chem["pinned"] is True
    assert chem.get("pin_moved") is True


def test_apply_pins_completed_course_pin_is_inert():
    future = [_emit_semester("FA 2026", [_named("IST 242")])]
    out = _apply_pins(future, {"course:GONE 101": "FA 2026"})  # no such future course
    assert len(out) == 1
    assert [c["course_code"] for c in out[0]["courses"]] == ["IST 242"]


def test_apply_pins_over_cap_bumps_unpinned_forward():
    # Six 3-cr courses = 18 cr (at cap); pinning a seventh in overflows → bump.
    base = [_named(f"C{i}") for i in range(6)]
    future = [
        _emit_semester("FA 2026", base),
        _emit_semester("SP 2027", [_named("PIN 100")]),
    ]
    out = _apply_pins(future, {"course:PIN 100": "FA 2026"})
    fa = next(s for s in out if s["term"] == "FA 2026")
    assert _semester_credits(fa["courses"]) <= _MAX_CREDITS
    # the pinned course stayed put; an unpinned one moved to the next term
    assert any(c["course_code"] == "PIN 100" and c["pinned"] for c in fa["courses"])
    later = next(s for s in out if s["term"] != "FA 2026")
    assert len(later["courses"]) >= 1


# ── business breadth slot universe ───────────────────────────────────────────

def test_breadth_slot_universe_excludes_own_area():
    from routers.courses import _resolve_slot_universe
    fin = "Finance, B.S. (Business)"
    allc = _resolve_slot_universe("pool:BUSINESS_BREADTH#s5", None, fin)
    codes = {c["course_code"] for c in allc}
    assert "MKTG 445" in codes                                  # other area included
    assert not any(c.startswith("FIN ") for c in codes)        # own area excluded


def test_breadth_slot_universe_area_scoped():
    from routers.courses import _resolve_slot_universe
    fin = "Finance, B.S. (Business)"
    mktg = _resolve_slot_universe("pool:BUSINESS_BREADTH#s5", "Marketing", fin)
    assert {c["course_code"] for c in mktg} == {"MKTG 327", "MKTG 330", "MKTG 422", "MKTG 445"}


# ── plain-python runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
