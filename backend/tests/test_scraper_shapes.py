"""
Tests for the bulletin shapes that made the catalog OVER-require.

Each was a way a list of electives got stored as individually required courses,
so the audit demanded far more than the bulletin does — Biology 272-495 credits
for a 50-55 credit option, Psychology's Business Option 183 for 24, Data
Sciences 620. Every fixture is a real bulletin section (tests/fixtures/req_*.html).

  * a qualifier before the number: "Select a minimum of 12 credits", "Select at least 6"
  * a pool header whose PROSE names a course ("... can be replaced by LA 495")
  * "pick one block": "Select one concentration", "Select an emphasis" (+ <h6>
    emphasis tables), "Select one sequence of the following", "Select course set A or B"
  * Application Focus lists published in the Suggested Academic Plan tab
  * options headed without the word "Option"

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_scraper_shapes.py -v
  * plain python:  cd backend && python tests/test_scraper_shapes.py

Hermetic — no network, no DynamoDB.
"""

import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from bs4 import BeautifulSoup

import scrape_psu
from routers.audit import _filter_rows, get_subplans  # noqa: F401  (get_subplans kept for parity)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _scrape(name: str) -> list[dict]:
    html = open(os.path.join(FIXTURES, f"req_{name}.html"), encoding="utf-8").read()
    original = scrape_psu.get_soup
    scrape_psu.get_soup = lambda url, retries=3: BeautifulSoup(html, "lxml")
    try:
        rows, _ = scrape_psu.scrape_program_requirements(
            {"url": "http://example.invalid/", "name": name, "college": "test"})
    finally:
        scrape_psu.get_soup = original
    return rows


def _group(rows, prefix):
    return [r for r in rows if r["requirement_group"].startswith(prefix)]


def _required(rows):
    return {r["course_code"] for r in rows if r["group_type"] == "required"}


def _pool_of(rows, code):
    """(threshold, members) of the pool holding `code`."""
    hit = next(r for r in rows if r["course_code"] == code
               and r["group_type"] in ("choose_credits", "choose_courses"))
    key = (hit["requirement_group"], hit["group_threshold"], hit["pool_seq"])
    members = {r["course_code"] for r in rows
               if (r["requirement_group"], r["group_threshold"], r["pool_seq"]) == key}
    return hit["group_threshold"], members


# ── Qualifier before the number ──────────────────────────────────────────────

def test_select_a_minimum_of_opens_a_pool():
    rows = _group(_scrape("biology"), "Neuroscience Option")
    # Only the five prescribed courses are required; the 400-level lists are a pool.
    assert _required(rows) == {"BIOL 469", "BMB 401", "BMB 402", "CHEM 210", "CHEM 212"}
    threshold, members = _pool_of(rows, "BIOL 404")
    assert threshold == 12 and {"BIOL 405", "PSYCH 452"} <= members


def test_header_regex_forms():
    ok = ["Select a minimum of 12 credits of 400-level biology courses",
          "Select at least 6 credits of ENVE Technical Electives from the following:",
          "Select 9 additional credits from the following", "Select 3-4 credits from:"]
    for t in ok:
        assert scrape_psu._POOL_HEADER.search(t), t
    # A cap limits part of a pool; it must never open one.
    assert not scrape_psu._POOL_HEADER.search("A maximum of 3 credits may be chosen from:")


# ── A header whose prose names a course ──────────────────────────────────────

def test_prose_course_in_a_header_is_not_a_course():
    rows = _scrape("psychology")
    business = _group(rows, "Business Option")
    assert "LA 495" not in {r["course_code"] for r in business}
    assert not _required(business)                       # 24-credit option, all choice
    threshold, members = _pool_of(business, "ECON 102")
    assert threshold == 15 and {"BA 301", "MKTG 301"} <= members
    # "not to include PSYCH 294" is an exclusion, never a requirement.
    assert "PSYCH 294" not in _required(rows)


# ── Pick one block ───────────────────────────────────────────────────────────

def test_select_one_concentration_is_one_pool():
    rows = _group(_scrape("secondary_ed"), "Social Studies Teaching Option")
    threshold, members = _pool_of(rows, "JST 121")
    # Courses from different concentrations share the one 15-credit pool.
    assert threshold == 15 and {"CAMS 1", "PLSC 7N"} <= members


def test_select_an_emphasis_spans_the_h6_emphasis_tables():
    rows = _group(_scrape("world_languages"), "Bilingual Education Teaching Option")
    threshold, members = _pool_of(rows, "FR 201")
    assert threshold == 33 and {"GER 201", "SPAN 110"} <= members
    assert _required(rows) <= {"WLED 414", "WLED 422", "WLED 444"}


def test_select_one_sequence_and_course_sets():
    history = _scrape("history")
    assert not {"HIST 1", "HIST 20"} & _required(history)
    physics = _group(_scrape("physics"), "Medical Physics Option")
    threshold, members = _pool_of(physics, "BIOL 110")
    assert threshold == 15 and "BIOL 141" in members     # Set A and Set B, one pool


# ── Application Focus lists + unnamed options ────────────────────────────────

def test_application_focus_lists_are_one_pool_not_required_groups():
    rows = _scrape("data_sciences_ist")
    groups = {r["requirement_group"] for r in rows}
    assert not groups & {"Psychology", "Food Science", "Economics", "Business Fundamentals"}
    applied = _group(rows, "Applied Data Sciences Option")
    threshold, members = _pool_of(applied, "ASTRO 120")
    assert threshold == 12 and "FDSC 200" in members


def test_options_without_the_word_option_are_named_as_options():
    groups = {r["requirement_group"] for r in _scrape("data_sciences_ist")}
    assert "Applied Data Sciences Option (DATSC_BS, DTSAB_BS): 47 credits" in groups
    # ...so a student with no option picked is narrowed to one of them.
    rows = _scrape("data_sciences_ist")
    kept = {r["requirement_group"] for r in _filter_rows(rows, None, set())}
    assert sum("Data Sciences Option" in g for g in kept) == 1


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
