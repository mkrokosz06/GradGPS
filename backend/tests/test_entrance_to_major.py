"""
Tests for Entrance to Major — the gate a student must clear to be admitted.

Entrance to Major was missing from GradGPS entirely: not one row in the 35k-row
catalog carried it, because it lives in prose under an <h2> rather than in a
courselist table, and the scraper only ever read tables.

The two things these tests exist to hold down:

  * the gate must never ADD requirements. Every course PSU names in it is
    already a requirement of the major, so it contributes ordering and urgency,
    never credits.
  * the gate must never be reported CLEARED when it is not. Half a compound
    branch, a grade below the bar, or a condition the bulletin states but we
    cannot check all have to fall short.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_entrance_to_major.py -v
  * plain python:  cd backend && python tests/test_entrance_to_major.py

Hermetic — parses saved fixtures of real bulletin sections, no network, no DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import entrance_to_major as etm
from entrance_parse import parse_entrance_section, parse_requirement

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _spec(name):
    with open(os.path.join(FIXTURES, f"etm_{name}.html"), encoding="utf-8") as fh:
        return parse_entrance_section(fh.read())


def _flat(spec):
    """Groups as readable strings: 'A OR B OR C+D'."""
    return ["/".join("+".join(b) for b in g) for g in spec["groups"]]


def _tx(code, status="done", grade="A", credits=3):
    return {"course_code": code, "status": status, "grade": grade,
            "credits_earned": credits, "credits": credits}


# ── Parsing: AND of OR-groups ────────────────────────────────────────────────

def test_eti_gate_groups():
    spec = _spec("eti")
    assert _flat(spec) == [
        "ETI 100/HCDD 113S/HCDD 113/CYBER 100/CYBER 100S/IST 110/A-I 100",
        "IST 140/CMPSC 121/CMPSC 131",
        "IST 210",
        "IST 220",
        "IST 242/CMPSC 122/CMPSC 132",
        "STAT 200/SCM 200",
    ]
    assert spec["gpa_min"] == 2.0
    assert spec["min_grade"] == "C"
    assert spec["has_unmodelled"] is False


def test_inline_annotations_do_not_split_a_group():
    """PSU annotates options inline — "HCDD 113S (FYS) or CYBER 100S (FYS)".
    Those bare parentheses used to split ETI's single 7-way alternative into
    three groups, which reads as "one from each of three lists": a gate three
    times harder than the real one."""
    groups = parse_requirement(
        "(«ETI 100» OR «HCDD 113S» (FYS) or «HCDD 113» or «CYBER 100S» (FYS) or «IST 110»)"
    )
    assert len(groups) == 1
    assert [b[0] for b in groups[0]] == [
        "ETI 100", "HCDD 113S", "HCDD 113", "CYBER 100S", "IST 110"
    ]


def test_flat_list_becomes_one_group_per_course():
    spec = _spec("astro")
    assert _flat(spec) == ["ASTRO 291", "CHEM 110", "MATH 140",
                           "MATH 141", "PHYS 211", "PHYS 212"]


def test_gpa_only_gate_has_no_courses():
    spec = _spec("aoj")
    assert spec["groups"] == []
    assert spec["gpa_min"] == 2.0
    assert spec["semester_standing"] == 3


# ── Parsing: compound branches ───────────────────────────────────────────────

def test_compound_branch_is_an_and_not_an_or():
    """Accounting's gate is "ACCTG 211 or ACCTG 211H or (ACCTG 201 and
    ACCTG 202)". Reading the inner pair as alternatives clears the gate for a
    student holding only ACCTG 201 — the direction that actually hurts."""
    spec = _spec("acctg")
    acctg = [g for g in spec["groups"] if any("ACCTG 211" in b for b in g)]
    assert len(acctg) == 1
    assert sorted(acctg[0], key=len) == [["ACCTG 211"], ["ACCTG 211H"],
                                         ["ACCTG 201", "ACCTG 202"]]


def test_parenthesised_or_is_a_group_not_a_branch():
    groups = parse_requirement("(«STAT 200» or «DS 200»)")
    assert groups == [[["STAT 200"], ["DS 200"]]]


def test_parenthesised_and_is_a_branch_of_the_surrounding_chain():
    groups = parse_requirement("«A 211» or «A 211H» or («A 201» and «A 202»)")
    assert len(groups) == 1
    assert groups[0] == [["A 211"], ["A 211H"], ["A 201", "A 202"]]


# ── Parsing: what we refuse to model ─────────────────────────────────────────

def test_enrollment_controls_flag_needs_confirmation():
    spec = _spec("aero")
    assert spec["has_unmodelled"] is True
    assert spec["notes"]


def test_non_course_conditions_flag_needs_confirmation():
    """World Languages requires 80 hours of documented work with learners. We
    cannot check that, and must not imply we did."""
    spec = _spec("wled")
    assert spec["has_unmodelled"] is True


def test_contradictory_gpa_figures_assert_neither():
    """Accounting names 3.10 for entrance and 2.60-3.09 for "space
    availability". Picking whichever matched first told the student the bar was
    2.60."""
    spec = _spec("acctg")
    assert spec["gpa_candidates"] == [2.6, 3.1]
    assert spec["gpa_min"] is None
    assert spec["has_unmodelled"] is True


def test_program_name_does_not_trip_the_unmodelled_check():
    """"Artificial Intelligence Methods and Applications" contains
    "Applications"; a bare substring match flagged the major off its own name."""
    spec = _spec("ai")
    assert spec["has_unmodelled"] is False


# ── The heading is not the anchor ────────────────────────────────────────────

def test_heading_wording_varies_by_program():
    """CourseLeaf calls this tab different things: "Entrance to Major" on ETI,
    "Direct Admission to the Major" on Nursing, "Entrance Procedures" on
    Architecture. Matching the heading text found the gate for 186 of the 225
    selectable majors and reported "no section" for the other 39 — every
    Nursing and Architecture program among them. The tab container id is the
    stable anchor."""
    for name, phrase in (("nursing", "Direct Admission to the Major"),
                         ("arch", "Entrance Procedures")):
        spec = _spec(name)
        assert phrase.lower() in spec["raw_text"].lower(), name


def test_application_based_gate_is_not_reported_as_no_requirements():
    """Architecture's gate is a portfolio and an external application. Reading
    "no courses, no GPA" as "no gate" would tell a student there is nothing to
    clear."""
    for name in ("arch", "nursing"):
        spec = _spec(name)
        assert spec["groups"] == []
        assert spec["has_unmodelled"] is True, name


# ── Evaluation ───────────────────────────────────────────────────────────────

def _evaluate(spec, transcript):
    etm._cache = {"P": spec}
    try:
        return etm.evaluate("P", transcript)
    finally:
        etm._cache = None


def test_one_alternative_clears_its_group():
    res = _evaluate(_spec("eti"), [_tx("SCM 200")])
    statuses = {g["options"][0]: g["status"] for g in res["groups"]}
    assert statuses["STAT 200"] == "done"
    assert statuses["IST 210"] == "missing"


def test_half_a_compound_branch_clears_nothing():
    res = _evaluate(_spec("acctg"), [_tx("ACCTG 201")])
    grp = next(g for g in res["groups"] if "ACCTG 211" in g["options"])
    assert grp["status"] == "partial"
    assert grp["status"] != "done"


def test_both_halves_of_a_compound_branch_clear_the_group():
    res = _evaluate(_spec("acctg"), [_tx("ACCTG 201"), _tx("ACCTG 202")])
    grp = next(g for g in res["groups"] if "ACCTG 211" in g["options"])
    assert grp["status"] == "done"


def test_a_grade_below_the_bar_does_not_clear():
    """The gate demands C or better. A D is not a pass here even though the
    course is on the transcript."""
    res = _evaluate(_spec("astro"), [_tx("CHEM 110", grade="D")])
    grp = next(g for g in res["groups"] if g["options"] == ["CHEM 110"])
    assert grp["status"] == "below_grade"
    assert res["status"] != "courses_met"


def test_in_progress_course_is_reported_as_in_progress():
    res = _evaluate(_spec("astro"), [_tx("CHEM 110", status="in_progress", grade="")])
    grp = next(g for g in res["groups"] if g["options"] == ["CHEM 110"])
    assert grp["status"] == "in_progress"


def test_all_groups_done_reports_courses_met():
    spec = _spec("astro")
    res = _evaluate(spec, [_tx(c) for g in spec["groups"] for c in g[0]])
    assert res["status"] == "courses_met"
    assert res["groups_done"] == res["groups_total"]


def test_unmodelled_condition_never_reports_met():
    """Even with every named course passed, a gate carrying a condition we
    cannot check reports needs_confirmation."""
    spec = _spec("aero")
    res = _evaluate(spec, [_tx(c) for g in spec["groups"] for c in g[0]])
    assert res["status"] == "needs_confirmation"
    assert res["needs_confirmation"] is True


def test_gpa_only_gate_reports_no_course_requirements():
    res = _evaluate(_spec("aoj"), [])
    assert res["status"] == "no_course_requirements"
    assert res["gpa_min"] == 2.0
    assert res["semester_standing"] == 3


def test_unknown_program_returns_none():
    etm._cache = {}
    try:
        assert etm.evaluate("Nothing, B.S.", []) is None
    finally:
        etm._cache = None


def test_missing_data_file_degrades_to_no_gate():
    """An unreadable bundled file must read as "no gate known", never a 500."""
    original = etm._DATA_PATH
    etm._cache = None
    etm._DATA_PATH = os.path.join(FIXTURES, "does-not-exist.json")
    try:
        assert etm.evaluate("Anything", []) is None
        assert etm.priority_codes("Anything") == set()
    finally:
        etm._DATA_PATH = original
        etm._cache = None


# ── Slot attachment (the checklist's write target) ───────────────────────────

def _slot(key, code, kind="course", options=None):
    s = {"slot_key": key, "course_code": code, "slot_kind": kind}
    if options is not None:
        s["options"] = [{"course_code": c} for c in options]
    return s


def test_group_maps_to_the_slot_offering_most_of_its_options():
    """Taking the first slot that matched anything picked `course:ETI 100` — a
    single named slot — over the slot offering seven of that group's
    alternatives. The checklist would then have had nothing to choose from."""
    gate = _evaluate(_spec("eti"), [])
    etm.attach_slots(gate, [
        _slot("course:ETI 100", "ETI 100"),
        _slot("one:CYBER 100|IST 110", "IST 110 or CYBER 100", "choose_one",
              ["IST 110", "CYBER 100"]),
    ])
    grp = gate["groups"][0]
    assert grp["slot_key"] == "one:CYBER 100|IST 110"
    assert grp["choosable"] == ["CYBER 100", "IST 110"]


def test_choosable_is_limited_to_what_the_slot_offers():
    """A gate can name a course the plan does not schedule. Offering it would
    write a choice against a slot that never lists it, so it would be ignored."""
    gate = _evaluate(_spec("eti"), [])
    etm.attach_slots(gate, [
        _slot("one:CYBER 100|IST 110", "IST 110 or CYBER 100", "choose_one",
              ["IST 110", "CYBER 100"]),
    ])
    grp = gate["groups"][0]
    assert "ETI 100" in grp["options"]          # the gate lists it
    assert "ETI 100" not in grp["choosable"]    # the slot does not offer it


def test_named_slot_is_pinnable_but_not_choosable():
    gate = _evaluate(_spec("eti"), [])
    etm.attach_slots(gate, [_slot("course:IST 210", "IST 210")])
    grp = next(g for g in gate["groups"] if g["options"] == ["IST 210"])
    assert grp["slot_key"] == "course:IST 210"
    assert grp["choosable"] == []


def test_satisfied_group_gets_no_slot():
    """Nothing to schedule, so nothing to write against."""
    gate = _evaluate(_spec("eti"), [_tx("SCM 200")])
    etm.attach_slots(gate, [_slot("course:SCM 200", "SCM 200")])
    grp = next(g for g in gate["groups"] if "STAT 200" in g["options"])
    assert grp["status"] == "done"
    assert "slot_key" not in grp


def test_attach_slots_tolerates_no_gate():
    assert etm.attach_slots(None, []) is None


# ── The gate adds no requirements ────────────────────────────────────────────

def test_priority_codes_are_only_candidates():
    """priority_codes feeds scheduling order, so it must list every course that
    could clear the gate — including alternatives the student will not take."""
    etm._cache = {"P": _spec("eti")}
    try:
        codes = etm.priority_codes("P")
    finally:
        etm._cache = None
    assert {"CYBER 100", "IST 110", "ETI 100", "A-I 100"} <= codes
    assert {"IST 210", "IST 220"} <= codes


def test_remaining_courses_excludes_cleared_groups():
    res = _evaluate(_spec("eti"), [_tx("SCM 200"), _tx("IST 210")])
    assert "STAT 200" not in res["remaining_courses"]
    assert "IST 210" not in res["remaining_courses"]
    assert "IST 220" in res["remaining_courses"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
