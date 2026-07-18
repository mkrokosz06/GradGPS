"""
Tests for the SAP scraper's HTML parser (scripts/scrape_sap.parse_plangrid).

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_scrape_sap.py -v
  * plain python:  cd backend && python tests/test_scrape_sap.py

Hermetic — parses a synthetic CourseLeaf sc_plangrid fixture, no network, no DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.scrape_sap import parse_plangrid, _classify

# A minimal CourseLeaf plan grid: two term-columns (Fall=Term0, Spring=Term1) of
# one year, exercising each cell shape.  Each <td> carries the `header` attribute
# CourseLeaf uses to pin its year/term.
_FIXTURE = """
<table class="sc_plangrid"><tbody>
<tr>
  <td class="codecol" header="year0 year0_Term0_codecol">
      <a onclick="return showCourse(this, 'PSU 6');">PSU 6</a></td>
  <td class="hourscol" header="year0 year0_Term0_hourscol">1</td>
  <td class="codecol" header="year0 year0_Term1_codecol">
      <a onclick="return showCourse(this, 'MGMT 301');">MGMT 301</a><sup>1,2</sup></td>
  <td class="hourscol" header="year0 year0_Term1_hourscol">3</td>
</tr>
<tr>
  <td class="codecol" header="year0 year0_Term0_codecol">
      CAS 100, <a onclick="return showCourse(this, 'ENGL 138T');">ENGL 138T</a> (GWS)</td>
  <td class="hourscol" header="year0 year0_Term0_hourscol">3</td>
  <td class="codecol" header="year0 year0_Term1_codecol">World Language - Level One</td>
  <td class="hourscol" header="year0 year0_Term1_hourscol">4</td>
</tr>
<tr>
  <td class="codecol" header="year0 year0_Term0_codecol">General Education Course (US)</td>
  <td class="hourscol" header="year0 year0_Term0_hourscol">3</td>
  <td class="codecol" header="year0 year0_Term1_codecol">ACCTG 4XX Accounting Elective</td>
  <td class="hourscol" header="year0 year0_Term1_hourscol">3</td>
</tr>
</tbody></table>
"""


def _sem(sems, season):
    return next(s for s in sems if s["term_season"] == season)


def test_parses_two_terms_with_correct_placement():
    sems = parse_plangrid(_FIXTURE)
    assert len(sems) == 2
    assert {s["term_season"] for s in sems} == {"FA", "SP"}
    assert all(s["year"] == 1 for s in sems)
    # Credits summed per term from the paired hourscol cells.
    assert _sem(sems, "FA")["credits"] == 7    # 1 + 3 + 3
    assert _sem(sems, "SP")["credits"] == 10   # 3 + 4 + 3


def test_single_course_slot():
    fa = _sem(parse_plangrid(_FIXTURE), "FA")
    psu = fa["slots"][0]
    assert psu["type"] == "course" and psu["code"] == "PSU 6" and psu["credits"] == 1


def test_choose_one_merges_plaintext_and_linked_codes():
    # 'CAS 100' is plain text, 'ENGL 138T' is a link — both must be captured.
    fa = _sem(parse_plangrid(_FIXTURE), "FA")
    speech = next(s for s in fa["slots"] if s["type"] == "choose_one")
    assert set(speech["codes"]) == {"CAS 100", "ENGL 138T"}
    assert speech["gen_ed"] == "GWS"


def test_gen_ed_and_pool_and_elective_classification():
    sems = parse_plangrid(_FIXTURE)
    fa, sp = _sem(sems, "FA"), _sem(sems, "SP")
    us = next(s for s in fa["slots"] if s["type"] == "gen_ed")
    assert us["category"] == "US"
    wl = next(s for s in sp["slots"] if s["type"] == "pool" and s["ref"] == "world_language")
    assert wl["credits"] == 4
    elec = next(s for s in sp["slots"] if s.get("ref") == "major_elective")
    assert elec["type"] == "pool"


def test_classify_bulletin_N_maps_to_GN():
    slot = _classify("General Education Course (N)", [], 3)
    assert slot["type"] == "gen_ed" and slot["category"] == "GN"


def test_classify_business_breadth_and_world_language():
    assert _classify("Business Breadth Course", [], 3)["ref"] == "business_breadth"
    assert _classify("World Language - Level Two (8th credit level)", [], 4)["ref"] == "world_language"


# Single-column variant: one column per YEAR (no Fall/Spring), header
# "yearN undefinedcodecol", with a per-year plangridsum total row.
_FIXTURE_SINGLE = """
<table class="sc_plangrid">
<thead><tr class="plangridyear firstrow"><th id="year0" colspan="1">First Year</th>
  <th id="year0" class="hourscol">Credits</th></tr></thead>
<tbody>
<tr><td class="codecol" header="year0 undefinedcodecol"><a onclick="return showCourse(this, 'PSU 6');">PSU 6</a></td>
    <td class="hourscol" header="year0 undefinedhourscol">1</td></tr>
<tr><td class="codecol" header="year0 undefinedcodecol"><a onclick="return showCourse(this, 'MATH 140');">MATH 140</a> (GQ)</td>
    <td class="hourscol" header="year0 undefinedhourscol">4</td></tr>
<tr><td class="codecol" header="year0 undefinedcodecol"><a onclick="return showCourse(this, 'CHEM 110');">CHEM 110</a></td>
    <td class="hourscol" header="year0 undefinedhourscol">3</td></tr>
<tr><td class="codecol" header="year0 undefinedcodecol"><a onclick="return showCourse(this, 'ENGL 15');">ENGL 15</a></td>
    <td class="hourscol" header="year0 undefinedhourscol">3</td></tr>
<tr><td class="codecol" header="year0 undefinedcodecol">General Education Course (US)</td>
    <td class="hourscol" header="year0 undefinedhourscol">3</td></tr>
<tr><td class="codecol" header="year0 undefinedcodecol">World Language - Level One</td>
    <td class="hourscol" header="year0 undefinedhourscol">4</td></tr>
<tr class="plangridsum"><td></td><td class="hourscol" header="year0 undefinedhourscol">18</td></tr>
</tbody></table>
"""


def test_single_column_year_splits_into_two_semesters():
    sems = parse_plangrid(_FIXTURE_SINGLE)
    assert len(sems) == 2
    assert [s["term_season"] for s in sems] == ["FA", "SP"]
    assert all(s["year"] == 1 for s in sems)
    # The year's 6 courses are split across the two semesters (none lost, none
    # duplicated), and the per-year plangridsum row (18) is NOT parsed as a slot.
    assert sum(len(s["slots"]) for s in sems) == 6
    assert round(sum(s["credits"] for s in sems), 1) == 18.0
    # Balanced-ish split preserving order: PSU 6 lands in the Fall half.
    assert sems[0]["slots"][0].get("code") == "PSU 6"
    assert 8 <= sems[0]["credits"] <= 13


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
