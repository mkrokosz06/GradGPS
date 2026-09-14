"""
Compound choose-one branches — "A or B or (C and D)".

PSU writes alternatives whose branches are themselves pairs of courses:

    Accounting - ACCTG 211 or ACCTG 211H or (ACCTG 201 and ACCTG 202)

A flat `pair_group_id` cannot express that. The scraper stored it as
choose_one(ACCTG 201, ACCTG 211), so a student holding only ACCTG 201 read as
FINISHED and the timeline never scheduled ACCTG 202 — the audit told them they
owed less than they did. Rows sharing a `pair_group_id` AND a non-empty
`pair_branch_id` now form one branch, satisfied only when every member is
done/in-progress.

The load-bearing test here is `test_legacy_choose_one_characterization`: with no
branch ids anywhere, the evaluator must behave EXACTLY as it did before. 31k
catalog rows carry no branch id and this ships to live beta users, so the engine
change has to be a provable no-op until data is patched.

Hermetic — no DynamoDB, no data files.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_compound_branches.py -v
  * plain python:  cd backend && python tests/test_compound_branches.py
"""

import os
import sys
import itertools

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit_engine as ae
from routers.timeline import _collect_missing


# ── Fixtures ─────────────────────────────────────────────────────────────────

_BASE = {"program_name": "Accounting, B.S. (Business)",
         "requirement_group": "Accounting",
         "group_type": "choose_one",
         "pair_group_id": 900}

# "ACCTG 211 or ACCTG 211H or (ACCTG 201 and ACCTG 202)"
COMPOUND = [
    {**_BASE, "course_code": "ACCTG 211",  "course_title": "Financial and Managerial", "credits": 4},
    {**_BASE, "course_code": "ACCTG 211H", "course_title": "…Honors",                  "credits": 4},
    {**_BASE, "course_code": "ACCTG 201",  "course_title": "Intro Financial",  "credits": 3, "pair_branch_id": "900a"},
    {**_BASE, "course_code": "ACCTG 202",  "course_title": "Intro Managerial", "credits": 3, "pair_branch_id": "900a"},
]

# No branch ids anywhere — a 2-way pair, a 3-way pair, and an unpaired row.
LEGACY = [
    {"course_code": "MATH 110", "course_title": "Tech Calc", "group_type": "choose_one", "pair_group_id": 1, "credits": 4},
    {"course_code": "MATH 140", "course_title": "Calc I",    "group_type": "choose_one", "pair_group_id": 1, "credits": 4},
    {"course_code": "CAS 100A", "course_title": "Speech A",  "group_type": "choose_one", "pair_group_id": 2, "credits": 3},
    {"course_code": "CAS 100B", "course_title": "Speech B",  "group_type": "choose_one", "pair_group_id": 2, "credits": 3},
    {"course_code": "CAS 100C", "course_title": "Speech C",  "group_type": "choose_one", "pair_group_id": 2, "credits": 3},
    {"course_code": "ENGL 15",  "course_title": "Rhetoric",  "group_type": "choose_one", "credits": 3},
]


def _taken(codes, status="done"):
    return {c: {"status": status, "grade": "B", "credits_earned": 3.0} for c in codes}


def _audit(rows, codes, status="done"):
    tx = [{"course_code": c, "status": status, "grade": "B", "credits_earned": 3.0}
          for c in codes]
    return ae.run_audit(rows, tx)


def _satisfied(rows, codes, status="done"):
    return _audit(rows, codes, status)["groups"][0]["satisfied"]


# ── The bug ──────────────────────────────────────────────────────────────────

def test_half_a_compound_branch_does_not_satisfy_the_requirement():
    """The whole point: ACCTG 201 alone is NOT the requirement."""
    assert _satisfied(COMPOUND, ["ACCTG 201"]) is False


def test_both_halves_of_a_compound_branch_satisfy_it():
    assert _satisfied(COMPOUND, ["ACCTG 201", "ACCTG 202"]) is True


def test_a_simple_branch_still_satisfies_it_alone():
    assert _satisfied(COMPOUND, ["ACCTG 211"]) is True
    assert _satisfied(COMPOUND, ["ACCTG 211H"]) is True


def test_nothing_taken_is_unsatisfied():
    assert _satisfied(COMPOUND, []) is False


def test_the_other_half_alone_also_fails():
    assert _satisfied(COMPOUND, ["ACCTG 202"]) is False


def test_in_progress_branch_counts_as_in_progress_not_done():
    g = _audit(COMPOUND, ["ACCTG 201", "ACCTG 202"], status="in_progress")["groups"][0]
    assert g["in_progress"] == 1 and g["done"] == 0


def test_mixed_done_and_in_progress_branch_is_in_progress():
    tx = [{"course_code": "ACCTG 201", "status": "done", "grade": "B", "credits_earned": 3.0},
          {"course_code": "ACCTG 202", "status": "in_progress", "grade": "", "credits_earned": 0}]
    g = ae.run_audit(COMPOUND, tx)["groups"][0]
    assert g["in_progress"] == 1 and g["done"] == 0


def test_compound_branch_credits_are_summed_not_single():
    """201+202 is 6 credits of progress, not 3."""
    assert _audit(COMPOUND, ["ACCTG 201", "ACCTG 202"])["credits_earned"] == 6.0


def test_branch_status_is_exposed_only_on_branch_rows():
    items = _audit(COMPOUND, ["ACCTG 201"])["groups"][0]["items"]
    by_code = {i["course_code"]: i for i in items}
    assert by_code["ACCTG 201"]["branch_status"] == "partial"
    assert by_code["ACCTG 201"]["pair_branch_id"] == "900a"
    # A plain alternative gains no new keys.
    assert "branch_status" not in by_code["ACCTG 211"]
    assert "pair_branch_id" not in by_code["ACCTG 211"]


# ── Timeline ─────────────────────────────────────────────────────────────────

def test_timeline_schedules_the_owed_half_of_a_started_branch():
    """
    The student picked the compound branch by taking ACCTG 201. The plan must
    surface ACCTG 202 as an ordinary course — and must NOT offer ACCTG 211,
    which is a choice they have already passed on.
    """
    slots = _collect_missing(_audit(COMPOUND, ["ACCTG 201"]))
    codes = [s["course_code"] for s in slots]
    assert codes == ["ACCTG 202"]
    assert slots[0]["slot_kind"] == "course"
    assert slots[0]["slot_key"] == "course:ACCTG 202"


def test_timeline_offers_a_choice_when_nothing_is_started():
    slots = _collect_missing(_audit(COMPOUND, []))
    assert len(slots) == 1 and slots[0]["slot_kind"] == "choose_one"


def test_timeline_schedules_nothing_once_the_branch_is_complete():
    assert _collect_missing(_audit(COMPOUND, ["ACCTG 201", "ACCTG 202"])) == []
    assert _collect_missing(_audit(COMPOUND, ["ACCTG 211"])) == []


# ── Backward compatibility — the guarantee ───────────────────────────────────

def _legacy_reference(rows: list[dict], taken: dict) -> dict:
    """
    Frozen copy of the pre-change pair loop (audit_engine._eval_choose_one as of
    commit 078fa87). Pinned here on purpose: if someone later changes the branch
    logic in a way that alters legacy behaviour, this disagrees and the test
    fails. Do not "fix" this to match new behaviour — that defeats the point.
    """
    from collections import defaultdict
    pairs, unpaired = defaultdict(list), []
    for row in rows:
        pid = row.get("pair_group_id")
        (pairs[str(pid)].append(row) if pid else unpaired.append(row))

    done = ip = missing = 0
    credits_earned = 0.0
    for pid, pair_rows in pairs.items():
        pair_status, best_credits = "missing", 0.0
        for row in pair_rows:
            code = row.get("course_code", "").strip().upper()
            status = ae._course_status(row, taken)
            if status == "done" and pair_status != "done":
                pair_status = "done"
                best_credits = taken.get(code, {}).get("credits_earned", 0)
            elif status == "in_progress" and pair_status == "missing":
                pair_status = "in_progress"
        if pair_status == "done":
            done += 1
            credits_earned += best_credits
        elif pair_status == "in_progress":
            ip += 1
        else:
            missing += 1
    for row in unpaired:
        code = row.get("course_code", "").strip().upper()
        status = ae._course_status(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
    return {"done": done, "in_progress": ip, "missing": missing,
            "credits_earned": credits_earned}


def test_legacy_choose_one_characterization():
    """
    All 3^6 = 729 done/in-progress/absent combinations over a branch-id-free
    fixture must match the frozen pre-change implementation exactly. This is
    what makes shipping the engine ahead of any data patch safe.
    """
    codes = [r["course_code"] for r in LEGACY]
    compared = 0
    for combo in itertools.product(["absent", "done", "in_progress"], repeat=len(codes)):
        taken = {c: {"status": st, "grade": "B", "credits_earned": 3.0}
                 for c, st in zip(codes, combo) if st != "absent"}
        got = ae._eval_choose_one(LEGACY, taken)
        want = _legacy_reference(LEGACY, taken)
        for field in ("done", "in_progress", "missing", "credits_earned"):
            assert got[field] == want[field], (combo, field, got[field], want[field])
        compared += 1
    assert compared == 729


def test_legacy_items_gain_no_new_keys():
    """An un-branched row must serialise exactly as before."""
    for item in ae._eval_choose_one(LEGACY, _taken(["MATH 140"]))["items"]:
        assert "pair_branch_id" not in item
        assert "branch_status" not in item


def test_gen_ed_twin_stays_in_lockstep():
    """
    _eval_choose_one_consumed is a near-duplicate 240 lines away. No gen-ed row
    carries a branch id today; this asserts the code path exists so the first
    one added doesn't silently evaluate under the old any-one-wins rule.
    """
    rows = [{**r, "pair_group_id": 900} for r in COMPOUND]
    taken = {"ACCTG 201": {"status": "done", "grade": "B", "credits_earned": 3.0,
                           "categories": set()}}
    res = ae._eval_choose_one_consumed(rows, taken)
    assert res["done"] == 0, "half a branch must not satisfy the gen-ed pair either"


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
