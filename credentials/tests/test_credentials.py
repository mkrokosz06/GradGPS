"""
Tests for the credential catalog pipeline.

Runs under pytest OR plain python, matching backend/tests/test_substitutions.py:

    python -m pytest tests/test_credentials.py
    python tests/test_credentials.py

Parser tests run against saved bulletin HTML in tests/fixtures/, so the suite is
offline and stable even when PSU edits a page.
"""

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from courseleaf import parse_courselist          # noqa: E402
from pools import parse_pool                     # noqa: E402
from validate import validate, credit_range      # noqa: E402
import dept_credits                              # noqa: E402

FIXTURES = HERE / "fixtures"


def _parse(name):
    return parse_courselist((FIXTURES / name).read_text(encoding="utf-8"))


def _groups_by_type(groups, gtype):
    return [g for g in groups if g["group_type"] == gtype]


# ── Pool sentences ───────────────────────────────────────────────────────────

def test_pool_departmental_with_sub_constraint():
    spec = parse_pool("Select 11 credits (at least 6 credits at the 400 level) in PSYCH", "11")
    assert spec.enumerable is False
    assert spec.dept == "PSYCH"
    assert spec.threshold == 11
    assert (spec.sub_credits, spec.sub_level) == (6, 400)
    # The sub-constraint must NOT become the pool's own floor: 100-level PSYCH
    # credits still count toward the 11.
    assert spec.min_level is None


def test_pool_level_range_and_exclusion():
    spec = parse_pool("Select 6 credits from the ANTH 400-489 range", "6")
    assert (spec.dept, spec.min_level, spec.max_level) == ("ANTH", 400, 489)

    spec = parse_pool("Select 3 credits from any ANTH course except ANTH 1", "3")
    assert spec.dept == "ANTH" and spec.exclude == ["ANTH 1"]


def test_pool_multi_subject():
    spec = parse_pool(
        "Select 3-6 credits at the 400 level from ACCTG, BA, BLAW, EBF, ECON, "
        "ENTR, FIN, FINSV, HPA, IB, LER, MIS, MGMT, MKTG, RM, SCM, or STAT", "3-6")
    assert spec.dept is None
    assert "ACCTG" in spec.depts and "STAT" in spec.depts and len(spec.depts) == 17
    assert (spec.threshold, spec.threshold_max, spec.min_level) == (3, 6, 400)


def test_pool_enumerable_marked_by_trailing_colon():
    spec = parse_pool("Select 2-7 credits from the following:", "2-7")
    assert spec.enumerable is True and (spec.threshold, spec.threshold_max) == (2, 7)


def test_adviser_dependent_sentence_is_not_guessed():
    # No rule can be derived from this — inventing one would auto-satisfy the
    # requirement, so it must stay unstructured.
    assert parse_pool("Select 3 credits in consultation with the minor adviser", "3") is None


def test_section_label_with_a_credit_total_is_not_a_pool():
    assert parse_pool("Additional Courses", "3") is None
    assert parse_pool("Environment or Climate Elective", "3") is None


# ── Page parsing ─────────────────────────────────────────────────────────────

def test_psychology_minor_recovers_the_departmental_pool():
    """The regression case: scrape_psu.py captured 7 of this minor's 18 credits
    because the "Select 11 credits … in PSYCH" row carries no course code."""
    groups, warnings = _parse("psychology-minor.html")
    required = _groups_by_type(groups, "required")
    dept     = _groups_by_type(groups, "dept_credits")

    assert [c["course_code"] for c in required[0]["courses"]] == ["PSYCH 100", "PSYCH 301W"]
    assert len(dept) == 1
    assert dept[0]["threshold"] == 11 and dept[0]["pool"]["dept"] == "PSYCH"
    assert credit_range(groups) == (18.0, 18.0)
    assert not warnings


def test_anthropology_minor_has_two_distinct_dept_pools():
    """Two pools in one section must stay separate — `run_audit` buckets by
    (group_type, threshold), so same-sized pools would otherwise merge."""
    groups, _ = _parse("anthropology-minor.html")
    dept = _groups_by_type(groups, "dept_credits")
    assert len(dept) == 2
    assert {g["threshold"] for g in dept} == {3, 6}
    assert len({g["name"] for g in dept}) == 2
    assert credit_range(groups) == (18.0, 18.0)


def test_arts_entrepreneurship_no_longer_requires_660_credits():
    """The over-require cascade: 208 pool options were read as individually
    required because the pool sentence was dropped and choose_one leaked."""
    groups, _ = _parse("arts-entrepreneurship-minor.html")
    lo, hi = credit_range(groups)
    assert lo < hi                     # the bulletin states ranges
    assert 12 <= lo and hi <= 30       # and the whole range is plausible now
    big = max(_groups_by_type(groups, "choose_credits"), key=lambda g: len(g["courses"]))
    assert len(big["courses"]) > 100   # the options are still all there …
    assert big["threshold"] <= 10      # … they're just options, not requirements


def test_no_unpaired_choose_one_rows_in_any_fixture():
    """An unpaired `choose_one` row is evaluated as individually required
    (audit_engine.py:1655) — the defect this parser exists to remove."""
    for f in sorted(FIXTURES.glob("*.html")):
        groups, _ = parse_courselist(f.read_text(encoding="utf-8"))
        for g in _groups_by_type(groups, "choose_one"):
            unpaired = [c["course_code"] for c in g["courses"] if not c["pair_group_id"]]
            assert not unpaired, f"{f.name}: {g['name']} has unpaired rows {unpaired}"


def test_or_alternatives_pair_up():
    groups, _ = _parse("service-enterprise-engineering-minor.html")
    lo, hi = credit_range(groups)
    assert (lo, hi) == (18.0, 18.0)


# ── Validation / quarantine ──────────────────────────────────────────────────

def test_validate_accepts_a_clean_credential():
    groups, _ = _parse("psychology-minor.html")
    blockers, warnings = validate({"kind": "minor", "groups": groups})
    assert blockers == [] and warnings == []


def test_validate_blocks_unpaired_choose_one():
    entry = {"kind": "minor", "groups": [{
        "name": "Requirements", "group_type": "choose_one", "min_grade": "",
        "threshold": None, "threshold_max": None, "pool": None,
        "courses": [{"course_code": "BA 100", "course_title": "x", "credits": 3,
                     "pair_group_id": None}],
    }]}
    blockers, _ = validate(entry)
    assert any("unpaired" in p for p in blockers)


def test_unusual_credit_total_warns_but_does_not_block():
    """A credit total is a smoke test, not a correctness requirement — some
    credentials really are unusual, so it must never withhold support on its own."""
    entry = {"kind": "minor", "groups": [{
        "name": "Requirements", "group_type": "required", "min_grade": "", "section": "R",
        "threshold": None, "threshold_max": None, "pool": None,
        "courses": [{"course_code": f"XX {i}00", "course_title": "x", "credits": 3,
                     "credits_max": None, "pair_group_id": None} for i in range(1, 9)] * 5,
    }]}
    blockers, warnings = validate(entry)
    assert blockers == []
    assert any("outside the typical" in w for w in warnings)


def test_unstructured_requirements_warn_but_do_not_block():
    """PSU genuinely defers these to an adviser, so no scraper will ever resolve
    them; the credential is still supported, with the gap surfaced."""
    groups, _ = _parse("art-minor.html")
    blockers, warnings = validate({"kind": "minor", "groups": groups})
    assert blockers == []
    assert any("must confirm" in w for w in warnings)
    # The credits are still counted, so the credential isn't ALSO flagged as too small.
    assert not any("outside the typical" in w for w in warnings)
    assert credit_range(groups) == (18.0, 18.0)


def test_subdivided_pool_is_not_double_counted():
    """"Select 12 credits …" followed by "Select 6 credits from the following:" with a
    blank credits cell is one 12-credit requirement, not 12 + 6."""
    groups = [
        {"name": "P", "group_type": "choose_credits", "section": "S", "min_grade": "",
         "threshold": 12, "threshold_max": None, "pool": None, "courses": [],
         "counts_toward_total": True},
        {"name": "P: sub", "group_type": "choose_credits", "section": "S", "min_grade": "",
         "threshold": 6, "threshold_max": None, "pool": None, "courses": [],
         "counts_toward_total": False},
    ]
    assert credit_range(groups) == (12.0, 12.0)


# ── dept_credits evaluation ──────────────────────────────────────────────────

def _taken(*pairs):
    return {code: {"status": st, "grade": "A", "credits_earned": cr}
            for code, st, cr in pairs}


def test_dept_pool_counts_only_matching_subject():
    spec = {"dept": "PSYCH", "threshold": 11}
    taken = _taken(("PSYCH 100", "done", 3), ("PSYCH 243", "done", 3),
                   ("HIST 100", "done", 3))
    r = dept_credits.evaluate(spec, taken, 11)
    assert r["credits_earned"] == 6 and r["satisfied"] is False
    assert {i["course_code"] for i in r["items"]} == {"PSYCH 100", "PSYCH 243"}


def test_dept_pool_level_sub_constraint_gates_satisfaction():
    """11 credits of 100-level PSYCH does not complete the Psychology minor."""
    spec = {"dept": "PSYCH", "sub_level": 400, "sub_credits": 6}
    low = _taken(("PSYCH 100", "done", 4), ("PSYCH 105", "done", 4), ("PSYCH 107", "done", 4))
    assert dept_credits.evaluate(spec, low, 11)["satisfied"] is False

    high = dict(low)
    high.update(_taken(("PSYCH 412", "done", 3), ("PSYCH 421", "done", 3)))
    assert dept_credits.evaluate(spec, high, 11)["satisfied"] is True


def test_dept_pool_respects_level_range_and_exclusions():
    spec = {"dept": "ANTH", "min_level": 400, "max_level": 489}
    taken = _taken(("ANTH 21", "done", 3), ("ANTH 412", "done", 3), ("ANTH 499", "done", 3))
    r = dept_credits.evaluate(spec, taken, 6)
    assert [i["course_code"] for i in r["items"]] == ["ANTH 412"]

    spec = {"dept": "ANTH", "exclude": ["ANTH 1"]}
    assert dept_credits.matches("ANTH 1", spec) is False
    assert dept_credits.matches("ANTH 21", spec) is True


def test_dept_pool_multi_subject_and_in_progress():
    spec = {"depts": ["ACCTG", "FIN"], "min_level": 400}
    taken = _taken(("ACCTG 471", "done", 3), ("FIN 410", "in_progress", 3),
                   ("MKTG 301", "done", 3), ("ACCTG 211", "done", 3))
    r = dept_credits.evaluate(spec, taken, 6)
    assert r["credits_earned"] == 3 and r["credits_in_progress"] == 3
    assert r["in_progress"] == 1


def test_dept_pool_does_not_double_count_alias_keys():
    """`_build_taken` registers alias codes (CRIMJ 100 and CRIM 100) pointing at the
    SAME dict; counting both would inflate the pool."""
    entry = {"status": "done", "grade": "A", "credits_earned": 3}
    taken = {"CRIM 100": entry, "CRIMJ 100": entry}
    r = dept_credits.evaluate({"depts": ["CRIM", "CRIMJ"]}, taken, 3)
    assert r["credits_earned"] == 3 and r["done"] == 1


def test_dept_pool_marks_consumed():
    spec = {"dept": "PSYCH"}
    taken = _taken(("PSYCH 100", "done", 3))
    consumed = set()
    dept_credits.evaluate(spec, taken, 3, consumed)
    assert consumed == {"PSYCH 100"}
    # A course already spent elsewhere is not counted twice.
    r = dept_credits.evaluate(spec, taken, 3, {"PSYCH 100"})
    assert r["credits_earned"] == 0


# ── Course-code cell shapes ──────────────────────────────────────────────────
# Every one of these was silently dropped by a single-code regex, and a dropped row
# removes a requirement from the credential with no warning — the largest source of
# under-counting found (African American Studies read as 15 credits instead of 18).

def test_cross_listed_codes_sharing_a_number():
    from courseleaf import _parse_code_cell
    assert _parse_code_cell("AFAM/WMNST 101N") == ("AFAM 101N", ["WMNST 101N"], [])
    assert _parse_code_cell("AGECO/ANSC/SOILS 418") == (
        "AGECO 418", ["ANSC 418", "SOILS 418"], [])


def test_cross_listed_codes_with_their_own_numbers():
    from courseleaf import _parse_code_cell
    assert _parse_code_cell("PHIL 132/RLST 131") == ("PHIL 132", ["RLST 131"], [])


def test_co_requisite_pair_is_one_requirement():
    from courseleaf import _parse_code_cell
    # The row's credit value covers the pair, so it must not become two requirements.
    assert _parse_code_cell("ANSC 207 & ANSC 208") == ("ANSC 207", [], ["ANSC 208"])


def test_hyphenated_subject_code():
    from courseleaf import _parse_code_cell
    assert _parse_code_cell("A-I 305") == ("A-I 305", [], [])


def test_or_prefix_and_non_codes():
    from courseleaf import _parse_code_cell
    assert _parse_code_cell("or ME 300")[0] == "ME 300"
    assert _parse_code_cell("Prescribed Courses")[0] is None
    assert _parse_code_cell("")[0] is None


def test_section_label_vs_requirement_row():
    from pools import is_section_label
    # A row restating its own section heading is a heading …
    assert is_section_label("Additional Courses", "Additional Courses")
    assert is_section_label("Total Credits", "Anything")
    # … but a short, label-shaped row that names something else is a requirement.
    assert not is_section_label("Environment or Climate Elective",
                                "Supporting Courses and Related Areas")


def test_choose_one_pair_uses_its_own_credits():
    """CMPEN 270 is a 4-credit course; assuming 3 per pair undercounted the minor."""
    groups = [{
        "name": "Additional", "group_type": "choose_one", "section": "A", "min_grade": "",
        "threshold": None, "threshold_max": None, "pool": None, "counts_toward_total": True,
        "courses": [
            {"course_code": "CMPEN 270", "course_title": "", "credits": 4,
             "credits_max": None, "pair_group_id": 1},
            {"course_code": "CMPEN 271", "course_title": "", "credits": None,
             "credits_max": None, "pair_group_id": 1},
        ],
    }]
    assert credit_range(groups) == (4.0, 4.0)


# ── Verification against PSU's own published total ───────────────────────────

def test_stated_total_from_program_requirements_table():
    from verify import stated_total
    total, source = stated_total((FIXTURES / "psychology-minor.html").read_text(encoding="utf-8"))
    assert total == 18 and source == "program-requirements table"


def test_reconstruction_agrees_with_psu_for_every_fixture():
    """The check that catches a parse which is well-formed but wrong — it is how the
    510-credit Environmental Inquiry reconstruction was found."""
    from verify import check, stated_total
    from validate import credit_range as cr
    checked = 0
    for f in sorted(FIXTURES.glob("*.html")):
        html = f.read_text(encoding="utf-8")
        if stated_total(html)[0] is None:
            continue
        groups, _ = parse_courselist(html)
        lo, hi = cr(groups)
        result = check({"credits": {"min": lo, "max": hi}}, html)
        assert result["agrees"], (
            f"{f.name}: reconstructed {lo}-{hi} but PSU states {result['stated_credits']}")
        checked += 1
    assert checked >= 4, "fixtures should cover several verifiable credentials"


# ── plain-python runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
