"""
Tests for the /courses/for-slot candidate resolver + search (class-selector
"search for a class" picker). Hermetic — the gen-ed cache is pre-populated so no
DynamoDB is touched.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_courses_for_slot.py -v
  * plain python:  cd backend && python tests/test_courses_for_slot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers import courses


def _seed_cache():
    us = [
        {"course_code": "SOC 119", "course_title": "Race and Ethnic Relations", "credits": 3.0, "multi_category": False},
        {"course_code": "AMST 100", "course_title": "American Cultures", "credits": 3.0, "multi_category": True},
    ]
    gn = [
        {"course_code": "ASTRO 1", "course_title": "Astronomical Universe", "credits": 3.0, "multi_category": False},
    ]
    courses._gen_ed_by_cat = {"US": us, "GN": gn}
    courses._gen_ed_all = us + gn


# ── _cat_token ───────────────────────────────────────────────────────────────

def test_cat_token_takes_leading_token():
    assert courses._cat_token("US: United States Cultures") == "US"
    assert courses._cat_token("GN: Natural Sciences") == "GN"
    assert courses._cat_token("") == ""


# ── _resolve_slot_universe ───────────────────────────────────────────────────

def test_resolve_named_category():
    _seed_cache()
    u = courses._resolve_slot_universe("gened:US")
    assert {c["course_code"] for c in u} == {"SOC 119", "AMST 100"}


def test_resolve_generic_is_union():
    _seed_cache()
    u = courses._resolve_slot_universe("gened:GENERAL#s3")
    assert {c["course_code"] for c in u} == {"SOC 119", "AMST 100", "ASTRO 1"}


def test_resolve_non_gened_slot_is_empty():
    _seed_cache()
    assert courses._resolve_slot_universe("course:IST 210") == []
    assert courses._resolve_slot_universe("one:MATH 110|MATH 140") == []


def test_resolve_category_override_switches_domain():
    _seed_cache()
    # A GN slot, but the student picks GA — search should target GN not the slot.
    u = courses._resolve_slot_universe("gened:US", category="GN")
    assert {c["course_code"] for c in u} == {"ASTRO 1"}


def test_resolve_world_language_pool():
    courses._lang_courses = [
        {"course_code": "SPAN 2", "course_title": "Intermediate Spanish", "credits": 4.0, "multi_category": False},
        {"course_code": "FR 2", "course_title": "Intermediate French", "credits": 4.0, "multi_category": False},
    ]
    u = courses._resolve_slot_universe("pool:WORLD_LANGUAGE#s5")
    assert {c["course_code"] for c in u} == {"SPAN 2", "FR 2"}
    courses._lang_courses = None


# ── courses_for_slot endpoint fn ─────────────────────────────────────────────

def test_search_filters_code_and_title():
    _seed_cache()
    r = courses.courses_for_slot(slot_key="gened:US", q="soc", limit=40, category=None, user_id="u1")
    assert [c["course_code"] for c in r["results"]] == ["SOC 119"]
    assert r["needs_query"] is False
    # title match works too
    r2 = courses.courses_for_slot(slot_key="gened:US", q="american", limit=40, category=None, user_id="u1")
    assert [c["course_code"] for c in r2["results"]] == ["AMST 100"]


def test_empty_query_small_universe_returns_all_sorted():
    _seed_cache()
    r = courses.courses_for_slot(slot_key="gened:US", q=None, limit=40, category=None, user_id="u1")
    assert [c["course_code"] for c in r["results"]] == ["AMST 100", "SOC 119"]
    assert r["needs_query"] is False


def test_empty_query_huge_universe_needs_query():
    # Only an unusually huge universe (>1600, i.e. the whole gen-ed union) gates
    # on a query; single domains auto-show. The client never asks for the union.
    big = [
        {"course_code": f"GEN {i}", "course_title": "x", "credits": 3.0, "multi_category": False}
        for i in range(1601)
    ]
    courses._gen_ed_by_cat = {}
    courses._gen_ed_all = big
    r = courses.courses_for_slot(slot_key="gened:GENERAL#s0", q=None, limit=40, category=None, user_id="u1")
    assert r["needs_query"] is True
    assert r["results"] == []


def test_empty_query_domain_sized_universe_auto_shows():
    # A big-but-domain-sized universe (e.g. IL ~1417) returns the full sorted list.
    mid = [
        {"course_code": f"IL {i:04d}", "course_title": "x", "credits": 3.0, "multi_category": False}
        for i in range(1417)
    ]
    courses._gen_ed_by_cat = {"IL": mid}
    courses._gen_ed_all = mid
    r = courses.courses_for_slot(slot_key="gened:IL", q=None, limit=500, category=None, user_id="u1")
    assert r["needs_query"] is False
    assert len(r["results"]) == 1417


def test_search_caps_at_limit():
    big = [
        {"course_code": f"SOC {i}", "course_title": "soc course", "credits": 3.0, "multi_category": False}
        for i in range(100)
    ]
    courses._gen_ed_by_cat = {"US": big}
    courses._gen_ed_all = big
    r = courses.courses_for_slot(slot_key="gened:US", q="soc", limit=10, category=None, user_id="u1")
    assert len(r["results"]) == 10


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
