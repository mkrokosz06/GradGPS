"""
Tests for timeline Layer 1 — pool expansion and credit-band packing.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_timeline_packing.py -v
  * plain python:  cd backend && python tests/test_timeline_packing.py

All tests are hermetic — no DynamoDB, no S3, no network. They exercise the pure
scheduling helpers in routers/timeline.py directly.
"""

import os
import sys

# Make the backend package importable when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.timeline import (
    _expand_pool,
    _slice_even,
    _sort_named,
    _build_future_semesters,
    _display_credits,
    _TARGET_CREDITS,
    _MAX_CREDITS,
    _GEN_ED_PER_SEM,
)


# ── _expand_pool ─────────────────────────────────────────────────────────────

def test_expand_pool_passes_through_non_pool():
    course = {"course_code": "ACCTG 211", "credits": 3}
    assert _expand_pool(course) == [course]


def test_expand_credits_pool_splits_into_3cr_slots_preserving_total():
    pool = {
        "course_code": "Free Electives",
        "course_title": "Choose 31 more elective credits",
        "credits": 31, "is_pool": True, "pool_needed_credits": 31,
    }
    slots = _expand_pool(pool)
    # 31 → ten 3-credit slots + one 1-credit slot
    assert len(slots) == 11
    assert sum(s["credits"] for s in slots) == 31
    assert all(s["is_pool"] for s in slots)
    # No slot carries more than a single ~3-credit course.
    assert all(s["credits"] <= 3 for s in slots)
    # Per-slot relabel: not every card repeats the whole-pool "31" figure.
    assert all("31" not in s["course_title"] for s in slots)
    # Per-slot pool_needed_credits matches the slot's own credits.
    assert {s["pool_needed_credits"] for s in slots} == {3, 1}


def test_expand_courses_pool_one_slot_per_course():
    pool = {
        "course_code": "Business Breadth", "course_title": "Choose 2 more course(s)",
        "credits": 3, "is_pool": True, "pool_needed_courses": 2,
    }
    slots = _expand_pool(pool)
    assert len(slots) == 2
    assert all(s["pool_needed_courses"] == 1 for s in slots)
    assert all(s["credits"] == 3 for s in slots)


def test_expand_pool_preserves_dropdown_and_gen_ed_keys():
    pool = {
        "course_code": "World Language", "credits": 6, "is_pool": True,
        "pool_needed_credits": 6,
        "pool_courses": [{"course_code": "SPAN 3", "course_title": "", "credits": 3}],
    }
    slots = _expand_pool(pool)
    assert len(slots) == 2
    assert all(s["pool_courses"] == pool["pool_courses"] for s in slots)


def test_expand_pool_handles_fractional_credits():
    pool = {"course_code": "X", "credits": 1.5, "is_pool": True, "pool_needed_credits": 1.5}
    slots = _expand_pool(pool)
    assert len(slots) == 1
    assert slots[0]["credits"] == 1.5


def test_expand_pool_zero_credit_pool_is_empty():
    assert _expand_pool({"is_pool": True, "pool_needed_credits": 0}) == []


# ── _slice_even ──────────────────────────────────────────────────────────────

def test_slice_even_preserves_order_and_count():
    items = list(range(18))
    groups = _slice_even(items, 8)
    assert len(groups) == 8
    # Sizes as even as possible: 18 over 8 → 2,2,2,3,2,2,2,3
    assert [len(g) for g in groups] == [2, 2, 2, 3, 2, 2, 2, 3]
    # Flattened, order is preserved and nothing is lost.
    assert [x for g in groups for x in g] == items


def test_slice_even_more_groups_than_items():
    groups = _slice_even([1, 2], 5)
    assert sum(len(g) for g in groups) == 2


# ── _sort_named ──────────────────────────────────────────────────────────────

def test_sort_named_orders_by_level():
    courses = [
        {"course_code": "ACCTG 471"}, {"course_code": "ECON 102"},
        {"course_code": "FIN 301"},   {"course_code": "MATH 110"},
    ]
    ordered = [c["course_code"] for c in _sort_named(courses)]
    # 100-level courses come before 300, which comes before 400.
    assert ordered.index("ECON 102") < ordered.index("FIN 301")
    assert ordered.index("MATH 110") < ordered.index("FIN 301")
    assert ordered.index("FIN 301") < ordered.index("ACCTG 471")


# ── _build_future_semesters ──────────────────────────────────────────────────

def _named(n, level=100, cr=3):
    return [{"course_code": f"SUBJ {level + i}", "course_title": "", "credits": cr}
            for i in range(n)]


def _gen_ed(n):
    return [{"course_code": f"GEN{i}", "course_title": "", "credits": 3,
             "is_pool": True, "gen_ed_categories": [f"CAT{i}"]} for i in range(n)]


def _upcoming(sems):
    """Academic (non-internship) upcoming semesters — summer internship terms excluded."""
    return [s for s in sems if s["status"] == "upcoming" and not s["term"].startswith("SU")]


def test_no_semester_exceeds_max_credits():
    named = _named(16)
    pool  = []
    for _ in range(1):
        pool += _expand_pool({"course_code": "Free Electives", "course_title": "elective",
                              "credits": 30, "is_pool": True, "pool_needed_credits": 30})
    sems = _build_future_semesters(named, _gen_ed(6), pool, "SP 2026")
    for s in _upcoming(sems):
        assert s["credits"] <= _MAX_CREDITS, f"{s['term']} = {s['credits']}cr over band"


def test_total_credits_preserved():
    named = _named(16)
    gened = _gen_ed(6)
    pool  = _expand_pool({"course_code": "Free Electives", "course_title": "elective",
                          "credits": 30, "is_pool": True, "pool_needed_credits": 30})
    expected = sum(_display_credits(c) for c in (*named, *gened, *pool))
    sems = _build_future_semesters(named, gened, pool, "SP 2026")
    got = sum(s["credits"] for s in sems)
    assert abs(got - expected) < 0.5


def test_named_courses_spread_not_front_loaded():
    # Named courses should reach the LAST academic semester rather than all
    # being crammed into the first few (the pre-fix bug: empty back half).
    named = _named(16)
    pool  = _expand_pool({"course_code": "Free Electives", "course_title": "elective",
                          "credits": 30, "is_pool": True, "pool_needed_credits": 30})
    sems = _upcoming(_build_future_semesters(named, _gen_ed(6), pool, "SP 2026"))
    last = sems[-1]
    assert any(not c.get("is_pool") for c in last["courses"]), \
        "last semester is all filler — named courses were front-loaded"


def test_no_semester_is_empty():
    sems = _build_future_semesters(_named(10), _gen_ed(4), [], "SP 2026")
    for s in sems:
        assert len(s["courses"]) > 0


def test_gen_ed_capped_per_semester():
    sems = _build_future_semesters(_named(8), _gen_ed(12), [], "SP 2026")
    for s in sems:
        n_ge = sum(1 for c in s["courses"] if c.get("gen_ed_categories"))
        assert n_ge <= _GEN_ED_PER_SEM


def test_fractional_credit_courses_packed_by_credit():
    # Two 1.5-credit courses should occupy one course-line's worth of credits,
    # not each burn a full 3-credit slot.
    named = [{"course_code": f"KINES {i}", "course_title": "", "credits": 1.5}
             for i in range(4)] + _named(8, level=200)
    sems = _build_future_semesters(named, [], [], "SP 2026")
    total = sum(s["credits"] for s in sems)
    assert abs(total - (4 * 1.5 + 8 * 3)) < 0.5


def test_internship_gets_its_own_summer_term():
    named = _named(12) + [{"course_code": "IST 495", "course_title": "Internship", "credits": 3}]
    internship = [c for c in named if c["course_code"] == "IST 495"]
    named = [c for c in named if c["course_code"] != "IST 495"]
    sems = _build_future_semesters(named, [], [], "SP 2026", internship)
    su = [s for s in sems if s["term"].startswith("SU")]
    assert len(su) == 1
    assert su[0]["courses"][0]["course_code"] == "IST 495"


def test_empty_inputs_produce_no_semesters():
    assert _build_future_semesters([], [], [], "SP 2026") == []


# ── Tiny runner so this works without pytest installed ──────────────────────

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
