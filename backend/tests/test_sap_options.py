"""
Tests for per-option Suggested Academic Plans.

A major with options publishes one plan grid per option, but only the first was
ever scraped, and load_template() handed it to every option — a Social Studies
teaching student was scheduled the Biology Teaching plan. These tests hold down:

  * a grid heading is matched to the catalog's option name (the value stored on
    the student's profile), despite PSU wording the two differently, and an
    ambiguous match is refused rather than guessed
  * only grids a University Park student follows are used
  * an option with no plan of its own gets the audit-driven planner, never
    another option's plan
  * a renamed course listed under both numbers is scheduled once (LA 83/283)

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_sap_options.py -v
  * plain python:  cd backend && python tests/test_sap_options.py

Hermetic — no DynamoDB, no network.
"""

import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

import plan_templates
from plan_templates import load_template, validate_template
from scrape_sap import (best_option_by_courses, collapse_renamed_duplicates, is_exact_option_match,
                        is_up_grid, match_option, page_option_codes, parse_grid_heading)

TEMPLATES = os.path.join(BACKEND, "sap_templates")


# ── Headings ─────────────────────────────────────────────────────────────────

def test_heading_splits_option_and_campus():
    assert parse_grid_heading(
        "Biology Teaching Option: Secondary Education, B.S. at University Park Campus") == \
        ("Biology Teaching", "University Park Campus")
    assert parse_grid_heading("Accounting, B.S. at University Park Campus") == \
        (None, "University Park Campus")


def test_only_grids_that_start_at_university_park():
    assert is_up_grid("University Park Campus")
    assert is_up_grid("University Park Campus and Commonwealth Campuses")
    assert is_up_grid("")
    assert not is_up_grid("Commonwealth Campuses")
    # A 2+2 plan that merely ENDS at University Park is not the UP plan.
    assert not is_up_grid("Berks Campus and Ending at University Park Campus")


# ── Matching a grid to the student's option ──────────────────────────────────

def test_reworded_headings_find_their_option():
    cases = {
        ("Biology Teaching", ("Biological Science Teaching", "Chemistry Teaching",
                              "Social Studies Teaching")): "Biological Science Teaching",
        ("Math", ("English 4-8", "Mathematics 4-8", "Social Studies 4-8")): "Mathematics 4-8",
        ("Graduate Studies", ("Computer Science", "Graduate Study")): "Graduate Study",
        ("Computational", ("Computation", "Electronics", "Medical Physics")): "Computation",
        ("French Language & Linguistics", ("Language and Culture", "Language and Linguistics",
                                           "Language and Literature")): "Language and Linguistics",
        ("Food & Biological Process Engineering",
         ("Agricultural Engineering", "Food and Biological Processing Engineering")):
            "Food and Biological Processing Engineering",
        ("Human Ecology/Cultural Anthropology", ("Biological Anthropology", "Human Ecology")):
            "Human Ecology",
        ("RN to BSN", ("RN to BSN", "Second Degree")): "RN to BSN",
    }
    for (grid, subplans), want in cases.items():
        assert match_option(grid, list(subplans)) == want, (grid, want)


def test_unselectable_and_ambiguous_grids_match_nothing():
    assert match_option("General", ["Ecology", "Neuroscience"]) is None
    assert match_option("General Biology", ["Ecology", "Plant Biology"]) is None
    # Equally good on both sides: refuse rather than pick one.
    assert match_option("Applied", ["Applied Statistics", "Applied Mathematics"]) is None


def test_exact_versus_reworded():
    assert is_exact_option_match("Atmospheric Sciences", "Atmospheric Science")
    assert is_exact_option_match("Math", "Mathematics 4-8")
    assert not is_exact_option_match("Biology Teaching", "Biological Science Teaching")


# ── The course witnesses ─────────────────────────────────────────────────────

def test_witness_uses_only_courses_unique_to_an_option():
    options = {"Biology Teaching": {"BIOL 110", "BIOL 220", "CHEM 110"},
               "Chemistry Teaching": {"CHEM 110", "CHEM 112", "CHEM 202"}}
    assert best_option_by_courses({"BIOL 220", "CHEM 110"}, options)[0] == "Biology Teaching"
    # Only shared courses: no signal, no ranking.
    assert best_option_by_courses({"CHEM 110"}, options) == []


def test_page_option_sections_are_read_from_the_requirements_tab():
    html = """<div id="programrequirementstextcontainer">
      <h4>Common Requirements for the Major (All Options)</h4>
      <a href="/search/?P=EDUC%20100">EDUC 100</a>
      <h5>French Teaching Option (36 credits)</h5>
      <a href="/search/?P=FR%20201">FR 201</a> <a href="/search/?P=FR%20202W">FR 202W</a>
      <h5>German Teaching Option (34 credits)</h5>
      <a href="/search/?P=GER%20201">GER 201</a>
      <h3>General Education</h3><a href="/search/?P=ENGL%2015">ENGL 15</a>
    </div>"""
    assert page_option_codes(html) == {"French Teaching": {"FR 201", "FR 202"},
                                       "German Teaching": {"GER 201"}}


# ── Renamed courses ──────────────────────────────────────────────────────────

def test_renamed_course_listed_twice_is_scheduled_once():
    sems = [{"credits": 4.5, "slots": [{"type": "course", "code": "LA 83", "credits": 1.5},
                                       {"type": "course", "code": "ECON 102", "credits": 3}]},
            {"credits": 4.5, "slots": [{"type": "course", "code": "LA 283", "credits": 1.5},
                                       {"type": "course", "code": "PSYCH 100", "credits": 3}]}]
    assert collapse_renamed_duplicates(sems) == [("LA 83", "LA 283")]
    codes = [s["code"] for sem in sems for s in sem["slots"]]
    assert codes.count("LA 283") == 1 and "LA 83" not in codes
    assert sems[1]["credits"] == 3


# ── load_template ────────────────────────────────────────────────────────────

def _with_templates(templates, fn):
    saved = plan_templates._all_templates
    plan_templates._all_templates = lambda: templates
    try:
        return fn()
    finally:
        plan_templates._all_templates = saved


def test_option_without_a_plan_gets_the_audit_planner_not_another_option():
    base = {"program_name": "Secondary Education, B.S.", "subplan": None, "id": "base"}
    bio = {"program_name": "Secondary Education, B.S.", "subplan": "Biological Science Teaching"}
    tpls = [base, bio]
    assert _with_templates(tpls, lambda: load_template(
        "Secondary Education, B.S.", "Biological Science Teaching")) is bio
    assert _with_templates(tpls, lambda: load_template(
        "Secondary Education, B.S.", "Social Studies Teaching")) is None
    assert _with_templates(tpls, lambda: load_template("Secondary Education, B.S.")) is base


def test_program_without_option_plans_keeps_its_shared_plan():
    base = {"program_name": "Accounting, B.S.", "subplan": None}
    assert _with_templates([base], lambda: load_template("Accounting, B.S.", "Anything")) is base


# ── The shipped templates ────────────────────────────────────────────────────

def _templates():
    for f in sorted(os.listdir(TEMPLATES)):
        yield f, json.load(open(os.path.join(TEMPLATES, f), encoding="utf-8"))


def test_every_option_template_is_valid_and_has_a_base():
    bases = {t["program_name"] for _, t in _templates() if not t.get("subplan")}
    for f, t in _templates():
        if t.get("subplan"):
            assert not validate_template(t), (f, validate_template(t))
            assert t["program_name"] in bases, f


def test_no_option_template_reintroduces_a_renamed_duplicate():
    from audit_engine import _MANUAL_RENAME_PAIRS
    for f, t in _templates():
        if not t.get("subplan") or not t.get("source_plan"):
            continue
        codes = [s.get("code") for sem in t["semesters"] for s in sem["slots"] if s.get("code")]
        for old, new in _MANUAL_RENAME_PAIRS:
            assert not (old in codes and new in codes), (f, old, new)


def test_one_template_per_program_and_option():
    seen = set()
    for f, t in _templates():
        key = (t["program_name"], t.get("subplan"))
        assert key not in seen, f
        seen.add(key)


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
