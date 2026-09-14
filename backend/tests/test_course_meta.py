"""
Tests for _get_course_meta — the course detail resolver behind GET /courses/{code}.

The same course has one catalog row per program that requires it, and those rows
disagree with each other. The resolver used to take whichever row the scan found
first, so MATH 140 could report "0 credits" (70 of its 478 rows carry no credits
value at all) and the mobile credits badge would hide itself.

Credits and titles now come from scripts/bulletin_courses.json — PSU's own
published numbers — with a majority vote across the catalog rows kept as the
fallback for anything the bulletin doesn't list. Both paths are covered below.

Hermetic — requirements_table.scan and the bulletin dict are both faked, so no
DynamoDB and no data file are touched.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_course_meta.py -v
  * plain python:  cd backend && python tests/test_course_meta.py
"""

import os
import sys
import asyncio
import pathlib
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers import courses


class _FakeTable:
    """Serves pre-baked scan pages, ignoring the filter (the rows ARE the matches)."""

    def __init__(self, pages):
        self.pages = pages
        self.scan_calls = 0

    def scan(self, **kw):
        self.scan_calls += 1
        idx = kw.get("ExclusiveStartKey", 0)
        page = self.pages[idx]
        out = {"Items": page}
        if idx + 1 < len(self.pages):
            out["LastEvaluatedKey"] = idx + 1
        return out


def _row(credits=None, title="Calculus", code="MATH 140"):
    r = {"course_code": code, "course_title": title}
    if credits is not None:
        r["credits"] = Decimal(str(credits))
    return r


def _meta(pages, code="MATH 140", bulletin=None):
    """
    Run _get_course_meta against faked scan pages and a faked bulletin, cold cache.
    `bulletin` defaults to empty, which forces the catalog-vote fallback path.
    """
    courses._course_cache.clear()
    real_tbl, real_bul = courses.requirements_table, courses._bulletin
    fake = _FakeTable(pages)
    courses.requirements_table = fake
    courses._bulletin = bulletin if bulletin is not None else {}
    try:
        return asyncio.run(courses._get_course_meta(code)), fake
    finally:
        courses.requirements_table = real_tbl
        courses._bulletin = real_bul
        courses._course_cache.clear()


# ── _mode ────────────────────────────────────────────────────────────────────

def test_mode_picks_most_frequent():
    assert courses._mode([3, 4, 4, 4, 3]) == 4


def test_mode_breaks_ties_toward_larger():
    assert courses._mode([3, 4]) == 4


def test_mode_of_empty_is_none():
    assert courses._mode([]) is None


# ── the bulletin path (authoritative) ────────────────────────────────────────

def test_bulletin_beats_the_catalog_rows():
    """
    The reason this exists: in production STAT 200 has 217 rows saying 3 against
    139 saying 4, so even a correct majority vote returns 3. The bulletin says 4.
    """
    meta, fake = _meta([[_row(3)] * 9],
                       code="STAT 200",
                       bulletin={"STAT 200": {"title": "Elementary Statistics", "credits": 4.0}})
    assert meta["credits"] == 4
    assert meta["course_title"] == "Elementary Statistics"
    assert fake.scan_calls == 0, "the bulletin hit should not touch DynamoDB at all"


def test_bulletin_range_gets_a_label():
    """KINES 1 is published as '1.5-3 Credits/Maximum of 12'."""
    meta, _ = _meta([[]], code="KINES 1",
                    bulletin={"KINES 1": {"title": "Introduction to Outdoor Pursuits",
                                          "credits": 1.5, "credits_max": 3.0}})
    assert meta["credits"] == 1.5
    assert meta["credits_label"] == "1.5-3"


def test_fixed_credits_label_has_no_range():
    meta, _ = _meta([[]], code="STAT 200",
                    bulletin={"STAT 200": {"title": "Elementary Statistics", "credits": 4.0}})
    assert meta["credits_label"] == "4"


def test_course_missing_from_bulletin_falls_back_to_the_vote():
    """IST 301 was renamed to ETI 301, so the current bulletin doesn't list it."""
    meta, fake = _meta([[_row(3, title="Information and Organizations", code="IST 301")]],
                       code="IST 301", bulletin={"STAT 200": {"title": "x", "credits": 4.0}})
    assert meta["credits"] == 3
    assert fake.scan_calls == 1


def test_bulletin_entry_without_credits_falls_back_to_the_vote():
    meta, fake = _meta([[_row(4)]], code="MATH 140",
                       bulletin={"MATH 140": {"title": "Calculus With Analytic Geometry I"}})
    assert meta["credits"] == 4
    assert fake.scan_calls == 1


def test_unreadable_bulletin_file_does_not_break_lookups():
    """A missing or corrupt data file must degrade to the vote, not 500."""
    courses._course_cache.clear()
    real_tbl, real_bul, real_path = (courses.requirements_table, courses._bulletin,
                                     courses._BULLETIN_PATH)
    courses.requirements_table = _FakeTable([[_row(4)]])
    courses._bulletin = None                       # force a re-read
    courses._BULLETIN_PATH = pathlib.Path("does-not-exist.json")
    try:
        meta = asyncio.run(courses._get_course_meta("MATH 140"))
        assert meta["credits"] == 4
    finally:
        courses.requirements_table, courses._bulletin = real_tbl, real_bul
        courses._BULLETIN_PATH = real_path
        courses._course_cache.clear()


# ── the catalog-vote fallback ────────────────────────────────────────────────

def test_null_credit_row_first_does_not_win():
    """The original failure: a credits-less row sorted first => '0 credits'."""
    meta, _ = _meta([[_row(None), _row(4), _row(4), _row(4)]])
    assert meta["credits"] == 4


def test_all_rows_null_falls_back_to_zero():
    meta, _ = _meta([[_row(None), _row(None)]])
    assert meta["credits"] == 0


# ── voting spans every page, not just the first ──────────────────────────────

def test_close_vote_counts_rows_on_later_pages():
    """
    STAT 200 really splits 182 rows saying 4 against 174 saying 3, and the
    bulletin says 4. Stopping early — or sampling only the first page — gets it
    wrong, because rows are laid out by program rather than shuffled.
    """
    page1 = [_row(3)] * 5           # an early page that leans the wrong way
    page2 = [_row(4)] * 6
    meta, fake = _meta([page1, page2])
    assert meta["credits"] == 4
    assert fake.scan_calls == 2, "must not stop at the first page"


def test_single_matching_row_is_used():
    meta, _ = _meta([[_row(3)]])
    assert meta["credits"] == 3


# ── value handling ───────────────────────────────────────────────────────────

def test_fractional_credits_are_not_truncated():
    """KINES 1 is 1.5 credits; int() would silently make it 1."""
    meta, _ = _meta([[_row(1.5), _row(1.5), _row(3)]])
    assert meta["credits"] == 1.5


def test_integral_credits_come_back_as_int():
    meta, _ = _meta([[_row(4)]])
    assert meta["credits"] == 4 and isinstance(meta["credits"], int)


def test_title_vote_ignores_blank_titles():
    meta, _ = _meta([[
        _row(4, title=""),
        _row(4, title="Calculus With Analytic Geometry I"),
        _row(4, title="Calculus With Analytic Geometry I"),
    ]])
    assert meta["course_title"] == "Calculus With Analytic Geometry I"


# ── misses and caching ───────────────────────────────────────────────────────

def test_unknown_course_returns_none():
    meta, _ = _meta([[]])
    assert meta is None


def test_result_is_cached():
    courses._course_cache.clear()
    real, real_bul = courses.requirements_table, courses._bulletin
    fake = _FakeTable([[_row(4)]])
    courses.requirements_table = fake
    courses._bulletin = {}
    try:
        asyncio.run(courses._get_course_meta("MATH 140"))
        calls_after_first = fake.scan_calls
        asyncio.run(courses._get_course_meta("MATH 140"))
        assert fake.scan_calls == calls_after_first, "second read should hit the cache"
    finally:
        courses.requirements_table = real
        courses._bulletin = real_bul
        courses._course_cache.clear()


def test_attribute_suffix_is_stripped_before_lookup():
    """IST 301W and IST 301 are the same catalog course."""
    meta, _ = _meta([[_row(3, title="Information and Organizations", code="IST 301")]],
                    code="IST 301W")
    assert meta["course_code"] == "IST 301"


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
