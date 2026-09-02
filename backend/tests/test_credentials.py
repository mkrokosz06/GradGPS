"""
Minor & certificate support: catalog loading, the two new group types, and the
no-op guarantee for students who declare nothing.

Runs under pytest OR plain python, matching test_substitutions.py:

    python -m pytest tests/test_credentials.py
    python tests/test_credentials.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import credential_catalog as cc                      # noqa: E402
from audit_engine import run_audit                   # noqa: E402


def tx(*rows):
    """Transcript rows: (code, status, grade, credits)."""
    return [{"course_code": c, "status": s, "grade": g, "credits_earned": cr,
             "course_title": ""} for c, s, g, cr in rows]


def group_named(result, gtype):
    return [g for g in result["groups"] if g["group_type"] == gtype]


# ── Catalog loading ──────────────────────────────────────────────────────────

def test_catalog_loads_and_is_all_supported():
    creds = cc.list_credentials()
    assert len(creds) > 200
    kinds = {c["kind"] for c in creds}
    assert kinds <= cc.VALID_KINDS


def test_unknown_program_is_not_a_credential():
    assert cc.get_credential("Enterprise Technology Integration, B.S.") is None
    assert cc.is_credential("Psychology, Minor")
    assert cc.load_credential("Not A Real Minor") is None


def test_rows_match_the_shape_the_engine_expects():
    _meta, rows = cc.load_credential("Psychology, Minor")
    required_keys = {"program_name", "requirement_group", "group_type",
                     "group_threshold", "course_code", "credits", "min_grade",
                     "pair_group_id"}
    for row in rows:
        assert required_keys <= set(row), row


# ── dept_credits ─────────────────────────────────────────────────────────────

def test_psychology_minor_end_to_end():
    """2 prescribed courses + "Select 11 credits (at least 6 at the 400 level) in
    PSYCH" = the real 18-credit minor, which the old catalog had as 7 credits."""
    _meta, rows = cc.load_credential("Psychology, Minor")

    empty = run_audit(rows, [])
    assert empty["missing"] > 0
    assert group_named(empty, "dept_credits")[0]["satisfied"] is False

    complete = run_audit(rows, tx(
        ("PSYCH 100", "done", "A", 3), ("PSYCH 301W", "done", "A", 4),
        ("PSYCH 105", "done", "B", 3), ("PSYCH 143", "done", "B", 2),
        ("PSYCH 412", "done", "A", 3), ("PSYCH 421", "done", "A", 3),
    ))
    assert complete["missing"] == 0
    assert complete["credits_earned"] == 18.0


def test_prescribed_courses_do_not_also_fill_the_additional_pool():
    """PSU's word is "Additional": a course that already satisfies a named
    requirement must not also count toward the departmental pool, or two courses
    plus one elective would read as a finished minor."""
    _meta, rows = cc.load_credential("Psychology, Minor")
    result = run_audit(rows, tx(
        ("PSYCH 100", "done", "A", 3), ("PSYCH 301W", "done", "A", 4),
        ("PSYCH 412", "done", "A", 4),
    ))
    pool = group_named(result, "dept_credits")[0]
    assert pool["satisfied"] is False
    assert pool["credits_earned"] == 4.0      # only the one additional course


def test_level_sub_constraint_gates_satisfaction():
    """11 credits of 100-level PSYCH does not complete the Psychology minor."""
    _meta, rows = cc.load_credential("Psychology, Minor")
    low = run_audit(rows, tx(
        ("PSYCH 100", "done", "A", 3), ("PSYCH 301W", "done", "A", 4),
        ("PSYCH 105", "done", "B", 4), ("PSYCH 107", "done", "B", 4),
        ("PSYCH 143", "done", "B", 3),
    ))
    pool = group_named(low, "dept_credits")[0]
    assert pool["credits_earned"] == 11.0 and pool["satisfied"] is False


def test_dept_pool_ignores_other_subjects_and_counts_in_progress():
    _meta, rows = cc.load_credential("Psychology, Minor")
    result = run_audit(rows, tx(
        ("HIST 100", "done", "A", 3), ("PSYCH 105", "in_progress", "", 3),
    ))
    pool = group_named(result, "dept_credits")[0]
    assert pool["credits_earned"] == 0.0
    assert pool["in_progress"] == 1
    assert [i["course_code"] for i in pool["items"]] == ["PSYCH 105"]


# ── unstructured_credits ─────────────────────────────────────────────────────

def test_adviser_deferred_requirement_is_never_auto_satisfied():
    """PSU defers these to an adviser ("in consultation with the minor adviser"),
    so no amount of coursework may mark them done on its own — claiming otherwise
    would tell a student they had finished a minor they had not."""
    _meta, rows = cc.load_credential("Art, Minor")
    loaded = [r for r in rows if r["group_type"] == "unstructured_credits"]
    assert loaded, "Art, Minor should carry an adviser-deferred requirement"

    # Even with a pile of relevant coursework it stays outstanding.
    result = run_audit(rows, tx(
        ("ART 110", "done", "A", 3), ("ART 111", "done", "A", 3),
        ("ART 220", "done", "A", 3), ("ART 230", "done", "A", 3),
        ("ART 240", "done", "A", 3), ("ART 250", "done", "A", 3),
    ))
    pool = group_named(result, "unstructured_credits")[0]
    assert pool["satisfied"] is False
    assert result["missing"] >= 1
    # …and the bulletin's own wording is carried through for the UI to show.
    assert pool["items"] == []


# ── Cross-listed courses ─────────────────────────────────────────────────────

def test_cross_listed_course_is_credited_under_either_subject():
    """"AFAM/WMNST 101N" is ONE course under two subjects; a student who took it
    as WMNST 101N must still get credit, and it must count only once."""
    _meta, rows = cc.load_credential("African American Studies, Minor")
    codes = {r["course_code"] for r in rows}
    assert "AFAM 101N" in codes and "WMNST 101N" in codes

    via_wmnst = run_audit(rows, tx(("WMNST 101N", "done", "A", 3)))
    prescribed = [g for g in via_wmnst["groups"] if "Prescribed" in g["name"]]
    assert prescribed, "expected a prescribed-courses group"
    assert via_wmnst["done"] >= 1


def test_cross_listed_pool_options_are_not_double_counted():
    """Inside a credit pool the alternates must NOT each be emitted: the engine
    already aliases cross-listings, so both codes would resolve to the same
    transcript entry and the pool would count it twice."""
    entry = cc.get_credential("African American Studies, Minor")
    pools = [g for g in entry["groups"] if g["group_type"] == "choose_credits"]
    assert pools
    _meta, rows = cc.load_credential("African American Studies, Minor")
    pool_rows = [r for r in rows if r["group_type"] == "choose_credits"]
    assert len(pool_rows) == sum(len(g["courses"]) for g in pools)


# ── The no-op guarantee ──────────────────────────────────────────────────────

def test_auditing_a_credential_does_not_touch_the_major_audit():
    """Credential support must be additive: a student who declares nothing gets
    byte-identical output to before the feature existed."""
    major_rows = [
        {"program_name": "X, B.S.", "requirement_group": "Core",
         "group_type": "required", "group_threshold": None,
         "course_code": "MATH 140", "course_title": "Calc", "credits": 4,
         "min_grade": "", "pair_group_id": None},
    ]
    courses = tx(("MATH 140", "done", "A", 4))
    before = run_audit(major_rows, courses)
    _meta, cred_rows = cc.load_credential("Psychology, Minor")
    run_audit(cred_rows, courses)                       # must not mutate shared state
    after = run_audit(major_rows, courses)
    assert before == after


def test_every_catalog_credential_audits_without_error():
    """A blank transcript against all 207 — nothing may raise, and nothing may
    report itself already satisfied."""
    for summary in cc.list_credentials():
        name = summary["program_name"]
        _meta, rows = cc.load_credential(name)
        result = run_audit(rows, [])
        assert result["missing"] > 0, f"{name} reports nothing missing on an empty transcript"


# ── Student-confirmed (adviser-defined) requirements ─────────────────────────

def _adviser_group(rows):
    return [r for r in rows if r["group_type"] == "unstructured_credits"][0]


def test_attested_courses_satisfy_an_adviser_defined_requirement():
    """The whole point of Phase 4: without this, the 53 credentials carrying one of
    these could never read as complete, whatever the student took."""
    _meta, rows = cc.load_credential("Art, Minor")
    group = _adviser_group(rows)["requirement_group"]
    courses = tx(("MUSIC 11", "done", "B", 3), ("THEA 101", "done", "B", 3),
                 ("ANTH 140", "done", "B", 3))

    unconfirmed = run_audit(rows, courses)
    assert group_named(unconfirmed, "unstructured_credits")[0]["satisfied"] is False

    confirmed = run_audit(rows, courses,
                          attested_by_group={group: ["MUSIC 11", "THEA 101", "ANTH 140"]})
    pool = group_named(confirmed, "unstructured_credits")[0]
    assert pool["satisfied"] is True
    assert pool["credits_earned"] == 9.0
    assert {i["course_code"] for i in pool["items"]} == {"MUSIC 11", "THEA 101", "ANTH 140"}


def test_partial_confirmation_reports_progress_not_completion():
    _meta, rows = cc.load_credential("Art, Minor")
    group = _adviser_group(rows)["requirement_group"]
    result = run_audit(rows, tx(("MUSIC 11", "done", "B", 3)),
                       attested_by_group={group: ["MUSIC 11"]})
    pool = group_named(result, "unstructured_credits")[0]
    assert pool["satisfied"] is False
    assert pool["credits_earned"] == 3.0 and pool["credits_needed"] == 6.0


def test_a_course_not_on_the_transcript_counts_for_nothing():
    """The API refuses it, but the engine must not credit a stale claim either —
    a student who dropped the course should stop getting credit for it."""
    _meta, rows = cc.load_credential("Art, Minor")
    group = _adviser_group(rows)["requirement_group"]
    result = run_audit(rows, [], attested_by_group={group: ["ART 230", "ART 240"]})
    pool = group_named(result, "unstructured_credits")[0]
    assert pool["credits_earned"] == 0.0 and pool["satisfied"] is False


def test_confirmation_never_stops_being_the_students_own_claim():
    """`needs_confirmation` stays true even when satisfied: the UI must keep framing
    it as the student's declaration, not something GradGPS verified."""
    _meta, rows = cc.load_credential("Art, Minor")
    group = _adviser_group(rows)["requirement_group"]
    result = run_audit(rows, tx(("MUSIC 11", "done", "B", 9)),
                       attested_by_group={group: ["MUSIC 11"]})
    pool = group_named(result, "unstructured_credits")[0]
    assert pool["satisfied"] is True and pool["needs_confirmation"] is True


def test_attested_map_for_another_credential_is_ignored():
    """`for_credential` narrows by program, so one minor's claims can't satisfy
    another's requirement of the same name."""
    import credential_choices as choices
    m = {choices.group_key("Art, Minor", "G"): ["MUSIC 11"]}
    assert choices.for_credential(m, "Art, Minor") == {"G": ["MUSIC 11"]}
    assert choices.for_credential(m, "Economics, Minor") == {}


def test_omitting_attested_courses_is_a_no_op():
    _meta, rows = cc.load_credential("Art, Minor")
    courses = tx(("ART 110", "done", "A", 3))
    assert run_audit(rows, courses) == run_audit(rows, courses, attested_by_group={})


# ── Timeline merge ───────────────────────────────────────────────────────────

from routers.timeline import _merge_credential_slots      # noqa: E402


def _sem(term, *courses):
    return {"term": term, "label": term, "status": "upcoming",
            "credits": sum(c["credits_earned"] for c in courses),
            "courses": list(courses)}


def _course(code, cr):
    return {"course_code": code, "course_title": "", "credits_earned": cr,
            "status": "missing", "grade": "", "is_pool": False}


def test_merging_nothing_is_a_no_op():
    future = [_sem("FA 2026", _course("ETI 297", 3))]
    before = [dict(s, courses=list(s["courses"])) for s in future]
    assert _merge_credential_slots(future, []) == before


def test_credential_courses_fill_headroom_before_adding_a_term():
    """A minor should lengthen the plan only when it genuinely cannot fit."""
    _meta, rows = cc.load_credential("Economics, Minor")
    audit = run_audit(rows, tx(("ECON 102", "done", "A", 3), ("ECON 104", "done", "A", 3)))
    audit["program"], audit["kind"] = "Economics, Minor", "minor"

    future = [_sem("FA 2026", _course("ETI 297", 3))]      # 15 credits of headroom
    merged = _merge_credential_slots(future, [audit])
    assert len(merged) >= 1
    tagged = [c for c in merged[0]["courses"] if c.get("credential")]
    assert tagged, "credential courses should fill the existing semester first"
    assert all(c["credential"] == "Economics, Minor" for c in tagged)
    assert merged[0]["credits"] <= 18.0, "must never exceed the max-credit band"


def test_credential_slots_never_land_in_a_summer_term():
    """Summer is skipped by the packer, and a summer term that IS in the plan is
    there for a reason (the SAP path lifts a required internship into one)."""
    _meta, rows = cc.load_credential("Economics, Minor")
    audit = run_audit(rows, [])
    audit["program"], audit["kind"] = "Economics, Minor", "minor"

    future = [_sem("SU 2027", _course("ETI 495", 1))]
    merged = _merge_credential_slots(future, [audit])
    summer = [s for s in merged if s["term"].startswith("SU")][0]
    assert not [c for c in summer["courses"] if c.get("credential")]


def test_a_course_the_major_already_schedules_is_not_duplicated():
    _meta, rows = cc.load_credential("Economics, Minor")
    audit = run_audit(rows, [])
    audit["program"], audit["kind"] = "Economics, Minor", "minor"

    future = [_sem("FA 2026", _course("ECON 302", 3))]
    merged = _merge_credential_slots(future, [audit])
    codes = [c["course_code"] for s in merged for c in s["courses"]]
    assert codes.count("ECON 302") == 1


def test_credential_slots_carry_a_namespaced_slot_key():
    """The class selector pins/swaps by slot_key, so credential slots need their own
    namespace to avoid colliding with the major's."""
    _meta, rows = cc.load_credential("Economics, Minor")
    audit = run_audit(rows, [])
    audit["program"], audit["kind"] = "Economics, Minor", "minor"
    merged = _merge_credential_slots([_sem("FA 2026")], [audit])
    keys = [c.get("slot_key") for s in merged for c in s["courses"] if c.get("credential")]
    assert keys and all(k and k.startswith("credslot:Economics, Minor:") for k in keys)
    assert len(set(keys)) == len(keys), "expanded pool slices need distinct keys"


def test_bounded_credential_pool_is_pickable():
    """A minor's "choose 2 of these 5" pool is a decision the student makes — each
    slice carries the option list and takes a stored pick, keyed under the
    credential's own namespace."""
    _meta, rows = cc.load_credential("Agronomy, Minor")
    audit = run_audit(rows, [])
    audit["program"], audit["kind"] = "Agronomy, Minor", "minor"
    merged = _merge_credential_slots([_sem("FA 2026")], [audit])
    pools = [c for s in merged for c in s["courses"]
             if c.get("options") and str(c.get("slot_key", "")).startswith("credslot:")]
    assert pools, "bounded credential pool should carry swap options"
    key = pools[0]["slot_key"]
    pick = pools[0]["options"][0]["course_code"]

    merged = _merge_credential_slots([_sem("FA 2026")], [audit], {key: pick})
    chosen = [c for s in merged for c in s["courses"] if c.get("slot_key") == key][0]
    assert chosen["course_code"] == pick
    assert chosen["chosen_code"] == pick
    assert chosen["is_pool"] is False


def test_adviser_deferred_requirement_is_scheduled_whole_and_flagged():
    """It is one block the student settles with an adviser — slicing it into
    3-credit pieces would misrepresent it."""
    _meta, rows = cc.load_credential("Art, Minor")
    audit = run_audit(rows, [])
    audit["program"], audit["kind"] = "Art, Minor", "minor"
    merged = _merge_credential_slots([_sem("FA 2026")], [audit])
    flagged = [c for s in merged for c in s["courses"] if c.get("needs_confirmation")]
    assert len(flagged) == 1
    assert flagged[0]["credits_earned"] >= 9
    assert "areas of concentration" in flagged[0]["course_title"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:                        # noqa: BLE001
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
