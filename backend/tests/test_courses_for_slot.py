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


# ── remaining_gen_ed_domains: removal + credit accounting ────────────────────

class _FakeTable:
    def __init__(self, items):
        self._items = items

    def query(self, **_kwargs):
        return {"Items": self._items}


def _seed_domains(*, tx=None, choices=None, audit_groups=None):
    """Wire the module's gen-ed catalog + patch its DB/audit deps for a hermetic
    remaining_gen_ed_domains() call. Returns nothing — mutates module globals."""
    courses._gen_ed_by_cat = {
        "GHW": [{"course_code": "KINES 1", "course_title": "Wellness", "credits": 1.5, "multi_category": False}],
        "GN":  [{"course_code": "ASTRO 1", "course_title": "Universe", "credits": 3.0, "multi_category": False}],
        "US":  [{"course_code": "SOC 119", "course_title": "Race", "credits": 3.0, "multi_category": False}],
    }
    courses._gen_ed_labels = {"GHW": "Health & Wellness", "GN": "Natural Sciences", "US": "US Cultures"}
    courses._gen_ed_rows = [{"program_name": "__GEN_ED__"}]  # truthy so the audit path runs
    courses.transcript_table = _FakeTable(tx or [])
    courses.run_gen_ed_audit = lambda rows, txc: {"groups": audit_groups or []}
    courses.get_user_choices = lambda uid: (choices or {})


_DEFAULT_GROUPS = [
    {"name": "GHW: Health & Wellness", "threshold": 3, "credits_earned": 1.5, "satisfied": False},
    {"name": "GN: Natural Sciences",   "threshold": 3, "credits_earned": 3.0, "satisfied": True},
    {"name": "US: United States Cultures", "threshold": 3, "credits_earned": 0.0, "satisfied": False},
]


def test_satisfied_domain_is_dropped_others_carry_credits():
    _seed_domains(audit_groups=_DEFAULT_GROUPS)
    out = courses.remaining_gen_ed_domains("u1")
    codes = [d["code"] for d in out]
    assert codes == ["GHW", "US"]            # GN (satisfied) dropped
    ghw = next(d for d in out if d["code"] == "GHW")
    assert ghw == {"code": "GHW", "label": "Health & Wellness",
                   "required": 3.0, "completed": 1.5, "selected": 0.0, "remaining": 1.5}


def test_selected_picks_cover_a_domain_and_hide_it():
    # 1.5 completed + a planned 1.5-cr GHW course = 3 → GHW is covered, hidden.
    choices = {"gened:GHW#1": {"slot_kind": "gen_ed", "chosen_course": "KINES 1"}}
    _seed_domains(audit_groups=_DEFAULT_GROUPS, choices=choices)
    out = courses.remaining_gen_ed_domains("u1")
    assert [d["code"] for d in out] == ["US"]


def test_exclude_slot_keeps_its_own_domain_visible():
    # Re-opening the very slot that holds the pick must still show GHW.
    choices = {"gened:GHW#1": {"slot_kind": "gen_ed", "chosen_course": "KINES 1"}}
    _seed_domains(audit_groups=_DEFAULT_GROUPS, choices=choices)
    out = courses.remaining_gen_ed_domains("u1", exclude_slot="gened:GHW#1")
    ghw = next((d for d in out if d["code"] == "GHW"), None)
    assert ghw is not None and ghw["selected"] == 0.0 and ghw["remaining"] == 1.5


def test_selected_pick_already_on_transcript_is_not_double_counted():
    choices = {"gened:GHW#1": {"slot_kind": "gen_ed", "chosen_course": "KINES 1"}}
    _seed_domains(audit_groups=_DEFAULT_GROUPS, choices=choices,
                  tx=[{"course_code": "KINES 1"}])
    out = courses.remaining_gen_ed_domains("u1")
    ghw = next(d for d in out if d["code"] == "GHW")
    assert ghw["selected"] == 0.0 and ghw["remaining"] == 1.5


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
