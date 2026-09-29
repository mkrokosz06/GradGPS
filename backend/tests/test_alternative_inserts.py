"""
Tests for the removal of unverified course alternatives.

`patch_known_alternatives(insert_missing=True)` inserted "the other course" into
every (program, group) holding half a known pair — CHEM 130 for CHEM 110 in
Chemical Engineering, MATH 110 for MATH 140 in Physics — whether or not that
program's bulletin offers it, so the audit told students they were done when
they were not. These tests hold down:

  * a verdict of `drop` needs EVERY source silent and a page we demonstrably read
  * removing an insert restores its partner exactly as scraped, and a student
    who took the partner course is unaffected
  * "ACCTG 211 or (ACCTG 201 and ACCTG 202)" is rebuilt as a branch, so ACCTG 201
    alone no longer satisfies it
  * the patch never re-inserts what was dropped
  * the cleanup is idempotent and its backup restores byte-for-byte

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_alternative_inserts.py -v
  * plain python:  cd backend && python tests/test_alternative_inserts.py

Hermetic — no DynamoDB, no network.
"""

import copy
import json
import os
import sys
import tempfile
from decimal import Decimal

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))

from audit_engine import run_audit
from verify_alternative_inserts import decide, expand, names, stated_branches
from remove_unverified_alternatives import apply, plan, restore

VERDICTS = os.path.join(BACKEND, "program_data", "alternative_inserts.json")

ALL_SILENT = {"bulletin_requirements": False, "bulletin_plan": False, "bulletin_entrance": False,
              "bulletin_page": False, "bulletin_links": False, "sap_template": False,
              "entrance_spec": False, "scraped_elsewhere": False}


# ── Reading the bulletin ─────────────────────────────────────────────────────

def test_abbreviated_lists_are_expanded():
    t = expand("ENGL 202C , 202A , 202B , or 202D (GWS) 3 PHYS 211 or 250 4")
    assert names("ENGL 202D", t) and names("PHYS 250", t)


def test_names_tolerates_one_attribute_letter_but_not_other_numbers():
    assert names("MATH 311W", "take MATH 311 in year two")
    assert names("MATH 311", "take MATH 311W in year two")
    assert not names("MATH 110", "take MATH 1100")
    assert not names("MATH 110", "CHEM 110H or CHEM 110")


def test_stated_branch_found_only_beside_its_partner():
    text = "courses: ACCTG 211 or ( ACCTG 201 and ACCTG 202 ), MGMT 301"
    assert stated_branches(text, "ACCTG 201", ["ACCTG 211"]) == [["ACCTG 201", "ACCTG 202"]]
    far = "( ACCTG 201 and ACCTG 202 ) " + "x " * 60 + "ACCTG 211"
    assert stated_branches(far, "ACCTG 201", ["ACCTG 211"]) == []


# ── The verdict ──────────────────────────────────────────────────────────────

def test_every_source_silent_drops():
    assert decide("CHEM 130", ["CHEM 110"], dict(ALL_SILENT), []) == ("drop", [])


def test_any_single_source_keeps():
    for source in ALL_SILENT:
        ev = dict(ALL_SILENT, **{source: True})
        assert decide("MATH 110", ["MATH 140"], ev, [])[0] == "keep", source


def test_unreadable_source_keeps():
    ev = dict(ALL_SILENT, bulletin_page=None)
    assert decide("MATH 110", ["MATH 140"], ev, [])[0] == "keep"


def test_page_that_does_not_name_the_partner_proves_nothing():
    assert decide("MATH 110", ["MATH 140"], dict(ALL_SILENT), [], page_sane=False)[0] == "keep"


def test_stated_compound_is_a_branch_even_if_mentioned_elsewhere():
    ev = dict(ALL_SILENT, bulletin_plan=True, bulletin_page=True)
    assert decide("ACCTG 201", ["ACCTG 211"], ev, [], [["ACCTG 201", "ACCTG 202"]]) == \
        ("branch", ["ACCTG 201", "ACCTG 202"])


def test_gate_branch_without_standalone_mention_is_a_branch():
    ev = dict(ALL_SILENT, bulletin_entrance=True, entrance_spec=True, bulletin_page=True)
    assert decide("ACCTG 201", ["ACCTG 211"], ev, [["ACCTG 201", "ACCTG 202"]])[0] == "branch"


# ── The cleanup plan ─────────────────────────────────────────────────────────

P, G = "Chemical Engineering, B.S.", "Requirements for the Major"


def _row(code, pid=None, gtype="choose_one", seq="#101", credits=3, **extra):
    r = {"program_name": P, "requirement_group": G, "course_code": code,
         "course_title": code, "credits": Decimal(credits), "group_type": gtype,
         "group_course": f"{G}#{code}{seq}"}
    if pid is not None:
        r["pair_group_id"] = Decimal(pid)
    r.update(extra)
    return r


def _entry(code, verdict, partner, pid=900, branch=()):
    return {"program": P, "group": G, "inserted": code, "group_course": f"{G}#{code}",
            "pair_group_id": pid, "partners": [partner], "verdict": verdict,
            "branch": list(branch), "evidence": dict(ALL_SILENT)}


def _apply_in_memory(ops, rows):
    rows = copy.deepcopy(rows)
    live = {(r["program_name"], r["group_course"]): r for r in rows}
    for op in ops:
        if op[0] == "delete":
            live.pop(op[1])
        elif op[0] == "put":
            live[(op[1]["program_name"], op[1]["group_course"])] = copy.deepcopy(op[1])
        else:
            _, key, set_fields, remove = op
            live[key].update(set_fields)
            for k in remove:
                live[key].pop(k, None)
    return list(live.values())


def _audit(rows, *codes):
    tx = [{"course_code": c, "status": "done", "grade": "A", "credits_earned": 3, "term": "FA 2025"}
          for c in codes]
    res = run_audit(rows, tx)
    return {i["course_code"]: i["status"] for g in res["groups"] for i in g["items"]}, res


def _pair_done(rows, *codes):
    res = run_audit(rows, [{"course_code": c, "status": "done", "grade": "A",
                            "credits_earned": 3, "term": "FA 2025"} for c in codes])
    return all(g.get("satisfied") for g in res["groups"])


def test_drop_deletes_insert_and_restores_partner_as_scraped():
    rows = [_row("CHEM 110", pid=900), _row("CHEM 130", pid=900, seq="")]
    ops, skipped = plan(rows, [_entry("CHEM 130", "drop", "CHEM 110")], {})
    assert not skipped
    after = _apply_in_memory(ops, rows)
    assert [r["course_code"] for r in after] == ["CHEM 110"]
    assert after[0]["group_type"] == "required" and "pair_group_id" not in after[0]


def test_drop_changes_the_audit_only_for_the_inserted_course():
    rows = [_row("CHEM 110", pid=900), _row("CHEM 130", pid=900, seq="")]
    ops, _ = plan(rows, [_entry("CHEM 130", "drop", "CHEM 110")], {})
    after = _apply_in_memory(ops, rows)
    # The student who took the real requirement is unaffected...
    assert _pair_done(rows, "CHEM 110") and _pair_done(after, "CHEM 110")
    # ...and the student who took the unoffered course is no longer told they're done.
    assert _pair_done(rows, "CHEM 130") and not _pair_done(after, "CHEM 130")


def test_plan_is_idempotent():
    rows = [_row("CHEM 110", pid=900), _row("CHEM 130", pid=900, seq="")]
    entries = [_entry("CHEM 130", "drop", "CHEM 110")]
    ops, _ = plan(rows, entries, {})
    again, skipped = plan(_apply_in_memory(ops, rows), entries, {})
    assert again == [] and skipped == []


def test_row_changed_since_verification_is_skipped_not_guessed():
    rows = [_row("CHEM 110", pid=901), _row("CHEM 130", pid=901, seq="")]   # pair id moved
    ops, skipped = plan(rows, [_entry("CHEM 130", "drop", "CHEM 110", pid=900)], {})
    assert ops == [] and skipped


def test_scraped_row_is_never_deleted():
    rows = [_row("CHEM 110", pid=900), _row("CHEM 130", pid=900, seq="#102")]   # has a sequence
    ops, skipped = plan(rows, [_entry("CHEM 130", "drop", "CHEM 110")], {})
    assert not [o for o in ops if o[0] == "delete"]


def test_three_way_pair_keeps_its_other_members_paired():
    rows = [_row("CAS 100A", pid=900), _row("CAS 100B", pid=900, seq=""),
            _row("CAS 100C", pid=900, seq="")]
    ops, _ = plan(rows, [_entry("CAS 100C", "drop", "CAS 100A")], {})
    after = _apply_in_memory(ops, rows)
    assert sorted(r["course_code"] for r in after) == ["CAS 100A", "CAS 100B"]
    assert all(r.get("pair_group_id") == Decimal(900) for r in after)


def test_keep_touches_nothing():
    rows = [_row("MATH 140", pid=900), _row("MATH 110", pid=900, seq="")]
    assert plan(rows, [_entry("MATH 110", "keep", "MATH 140")], {}) == ([], [])


def test_branch_makes_half_a_sequence_insufficient():
    rows = [_row("ACCTG 211", pid=900, credits=4), _row("ACCTG 201", pid=900, seq="")]
    entry = _entry("ACCTG 201", "branch", "ACCTG 211", branch=["ACCTG 201", "ACCTG 202"])
    bulletin = {"ACCTG 202": {"title": "Managerial Accounting", "credits": 3}}
    ops, skipped = plan(rows, [entry], bulletin)
    assert not skipped
    after = _apply_in_memory(ops, rows)
    assert _pair_done(rows, "ACCTG 201")                  # the bug
    assert not _pair_done(after, "ACCTG 201")             # half the branch: not done
    assert _pair_done(after, "ACCTG 201", "ACCTG 202")    # the whole branch: done
    assert _pair_done(after, "ACCTG 211")                 # the other alternative: done
    assert plan(after, [entry], bulletin) == ([], [])     # idempotent


# ── Backup + restore ─────────────────────────────────────────────────────────

class FakeTable:
    def __init__(self, rows):
        self.items = {(r["program_name"], r["group_course"]): copy.deepcopy(r) for r in rows}

    def delete_item(self, Key):
        self.items.pop((Key["program_name"], Key["group_course"]), None)

    def put_item(self, Item):
        self.items[(Item["program_name"], Item["group_course"])] = copy.deepcopy(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues=None):
        item = self.items[(Key["program_name"], Key["group_course"])]
        vals = ExpressionAttributeValues or {}
        for part in UpdateExpression.split("REMOVE"):
            part = part.strip()
            if part.startswith("SET"):
                for assign in part[3:].split(","):
                    n, v = [s.strip() for s in assign.split("=")]
                    item[ExpressionAttributeNames[n]] = vals[v]
            elif part:
                for n in part.split(","):
                    item.pop(ExpressionAttributeNames[n.strip()], None)


def test_apply_then_restore_round_trips_exactly():
    rows = [_row("ACCTG 211", pid=900, credits=4), _row("ACCTG 201", pid=900, seq=""),
            _row("CHEM 110", pid=901), _row("CHEM 130", pid=901, seq="")]
    entries = [_entry("ACCTG 201", "branch", "ACCTG 211", branch=["ACCTG 201", "ACCTG 202"]),
               _entry("CHEM 130", "drop", "CHEM 110", pid=901)]
    ops, _ = plan(rows, entries, {"ACCTG 202": {"title": "Managerial Accounting", "credits": 3}})
    table = FakeTable(rows)
    original = copy.deepcopy(table.items)
    with tempfile.TemporaryDirectory() as d:
        backup = os.path.join(d, "b.json")
        apply(ops, table, rows, backup)
        assert table.items != original
        assert sorted(r["course_code"] for r in table.items.values()) == \
            ["ACCTG 201", "ACCTG 202", "ACCTG 211", "CHEM 110"]
        restore(table, backup)
    assert table.items == original


# ── The shipped verdicts file ────────────────────────────────────────────────

def _verdicts():
    return json.load(open(VERDICTS, encoding="utf-8"))["entries"]


def test_every_drop_is_silent_in_every_source_on_a_page_we_read():
    for e in _verdicts():
        if e["verdict"] == "drop":
            assert not any(e["evidence"].values()), e
            assert e["page_names_partner"], e


def test_every_verdict_was_actually_verified():
    for e in _verdicts():
        assert None not in e["evidence"].values(), e


def test_text_and_html_link_witnesses_agree():
    for e in _verdicts():
        assert e["evidence"]["bulletin_page"] == e["evidence"]["bulletin_links"], e


def test_branches_have_a_partner_and_two_members():
    for e in _verdicts():
        if e["verdict"] == "branch":
            assert len(e["branch"]) >= 2 and e["inserted"] in e["branch"] and e["partners"], e


def test_patch_only_inserts_verified_alternatives():
    from seed_matthew import _verified_inserts
    verified = _verified_inserts()
    for e in _verdicts():
        key = (e["program"], e["group"], e["inserted"])
        assert (key in verified) == (e["verdict"] != "drop"), key


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
