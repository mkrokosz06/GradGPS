"""
Tests for degree audit + gen-ed audit core behaviors.

Hermetic — no DynamoDB. Covers:
  * choose_one + pair_group_id / pair_status
  * choose_credits as a single requirement slot (_pool_counts)
  * Writing Across the Curriculum (writing_intensive / is_writing)
  * Gen-ed cross-group exclusivity + multi_category exception

Runnable:
  cd backend && python -m pytest tests/test_audit_engine.py -v
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_engine import _pool_counts, run_audit, run_gen_ed_audit


def _req(
    *,
    program: str,
    group: str,
    gtype: str,
    code: str,
    credits: float = 3.0,
    threshold=None,
    pair_group_id=None,
    multi_category: bool = False,
    title: str = "",
) -> dict:
    row = {
        "program_name": program,
        "requirement_group": group,
        "group_type": gtype,
        "course_code": code,
        "course_title": title or code,
        "credits": credits,
        "group_course": f"{group}#{code}",
    }
    if threshold is not None:
        row["group_threshold"] = threshold
    if pair_group_id is not None:
        row["pair_group_id"] = pair_group_id
    if multi_category:
        row["multi_category"] = True
    return row


def _tx(code: str, *, status: str = "done", grade: str = "A", credits: float = 3.0, is_writing: bool = False) -> dict:
    return {
        "course_code": code,
        "status": status,
        "grade": grade,
        "credits_earned": credits,
        "is_writing": is_writing,
    }


def _group(result: dict, name: str) -> dict:
    for g in result["groups"]:
        if g["name"] == name:
            return g
    raise AssertionError(f"group not found: {name!r} in {[g['name'] for g in result['groups']]}")


# ── choose_one / pair_group_id ───────────────────────────────────────────────

def test_choose_one_pair_satisfied_by_either_alternative():
    major = "Test Major, B.S."
    rows = [
        _req(program=major, group="Math", gtype="choose_one", code="MATH 110", pair_group_id=580),
        _req(program=major, group="Math", gtype="choose_one", code="MATH 140", pair_group_id=580, credits=4),
    ]
    # Only MATH 140 taken — pair should be done
    result = run_audit(rows, [_tx("MATH 140", credits=4)])
    g = _group(result, "Math")
    assert g["satisfied"] is True
    assert g["done"] == 1
    assert g["missing"] == 0
    assert all(item["pair_status"] == "done" for item in g["items"])


def test_choose_one_pair_missing_when_neither_taken():
    major = "Test Major, B.S."
    rows = [
        _req(program=major, group="Math", gtype="choose_one", code="MATH 110", pair_group_id=580),
        _req(program=major, group="Math", gtype="choose_one", code="MATH 140", pair_group_id=580, credits=4),
    ]
    result = run_audit(rows, [])
    g = _group(result, "Math")
    assert g["satisfied"] is False
    assert g["missing"] == 1
    assert all(item["pair_status"] == "missing" for item in g["items"])


def test_choose_one_in_progress_counts_as_pair_in_progress():
    major = "Test Major, B.S."
    rows = [
        _req(program=major, group="Physics", gtype="choose_one", code="PHYS 211", pair_group_id=600, credits=4),
        _req(program=major, group="Physics", gtype="choose_one", code="PHYS 250", pair_group_id=600, credits=4),
    ]
    result = run_audit(rows, [_tx("PHYS 250", status="in_progress", credits=4)])
    g = _group(result, "Physics")
    assert g["satisfied"] is False
    assert g["in_progress"] == 1
    assert g["missing"] == 0
    assert all(item["pair_status"] == "in_progress" for item in g["items"])


# ── choose_credits as one slot ───────────────────────────────────────────────

def test_choose_credits_satisfied_at_threshold():
    major = "Test Major, B.S."
    rows = [
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 301", threshold=6),
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 305", threshold=6),
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 406", threshold=6),
    ]
    # 3 + 3 = 6 credits → satisfied
    result = run_audit(rows, [_tx("FIN 301"), _tx("FIN 305")])
    g = _group(result, "Electives")
    assert g["satisfied"] is True
    assert g["credits_earned"] >= 6


def test_choose_credits_pool_counts_as_single_slot_when_missing():
    """Unchosen electives must not inflate global missing count item-by-item."""
    major = "Test Major, B.S."
    rows = [
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 301", threshold=9),
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 305", threshold=9),
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 406", threshold=9),
    ]
    result = run_audit(rows, [])
    # Pool missing → exactly one missing slot globally, not 3
    assert result["missing"] == 1
    assert result["done"] == 0
    g = _group(result, "Electives")
    d, ip, m = _pool_counts("choose_credits", {
        "satisfied": g["satisfied"],
        "done": g["done"],
        "in_progress": g["in_progress"],
        "missing": g["missing"],
    })
    assert (d, ip, m) == (0, 0, 1)


def test_choose_credits_pool_counts_as_single_slot_when_satisfied():
    major = "Test Major, B.S."
    rows = [
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 301", threshold=6),
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 305", threshold=6),
        _req(program=major, group="Electives", gtype="choose_credits", code="FIN 406", threshold=6),
    ]
    result = run_audit(rows, [_tx("FIN 301"), _tx("FIN 305")])
    assert result["done"] == 1
    assert result["missing"] == 0


# ── Writing Across the Curriculum ────────────────────────────────────────────

def test_wac_satisfied_by_writing_flagged_credits():
    rows = [
        _req(
            program="__GEN_ED__",
            group="Writing Across the Curriculum",
            gtype="writing_intensive",
            code="WAC",
            threshold=3,
        ),
    ]
    transcript = [
        _tx("ETI 300W", credits=3, is_writing=True),
        _tx("HIST 100", credits=3, is_writing=False),
    ]
    result = run_gen_ed_audit(rows, transcript)
    g = _group(result, "Writing Across the Curriculum")
    assert g["satisfied"] is True
    assert g["group_type"] == "writing_intensive"
    assert result["done"] == 1  # single pool slot


def test_wac_not_satisfied_without_writing_flag():
    rows = [
        _req(
            program="__GEN_ED__",
            group="Writing Across the Curriculum",
            gtype="writing_intensive",
            code="WAC",
            threshold=3,
        ),
    ]
    # Same course code pattern but is_writing False → does not count
    result = run_gen_ed_audit(rows, [_tx("ETI 300W", credits=3, is_writing=False)])
    g = _group(result, "Writing Across the Curriculum")
    assert g["satisfied"] is False
    assert result["missing"] == 1


# ── Gen-ed exclusivity ───────────────────────────────────────────────────────

def test_gen_ed_course_cannot_satisfy_two_groups():
    rows = [
        _req(program="__GEN_ED__", group="GA", gtype="choose_credits", code="ART 10", threshold=3),
        _req(program="__GEN_ED__", group="GH", gtype="choose_credits", code="ART 10", threshold=3),
    ]
    result = run_gen_ed_audit(rows, [_tx("ART 10")])
    ga = _group(result, "GA")
    gh = _group(result, "GH")
    # Required/choose processed first by priority; choose_credits ordered equally —
    # first group in sorted order claims ART 10; second sees it consumed.
    satisfied = [ga["satisfied"], gh["satisfied"]]
    assert satisfied.count(True) == 1
    assert satisfied.count(False) == 1


def test_gen_ed_multi_category_can_satisfy_two_groups():
    rows = [
        _req(
            program="__GEN_ED__",
            group="GA",
            gtype="choose_credits",
            code="ART 20N",
            threshold=3,
            multi_category=True,
        ),
        _req(
            program="__GEN_ED__",
            group="GH",
            gtype="choose_credits",
            code="ART 20N",
            threshold=3,
            multi_category=True,
        ),
    ]
    result = run_gen_ed_audit(rows, [_tx("ART 20N")])
    assert _group(result, "GA")["satisfied"] is True
    assert _group(result, "GH")["satisfied"] is True


def test_wac_does_not_consume_course_from_domain_pool():
    """A writing course still counts toward its knowledge domain AND WAC."""
    rows = [
        _req(program="__GEN_ED__", group="GH", gtype="choose_credits", code="ENGL 202W", threshold=3),
        _req(
            program="__GEN_ED__",
            group="Writing Across the Curriculum",
            gtype="writing_intensive",
            code="WAC",
            threshold=3,
        ),
    ]
    result = run_gen_ed_audit(rows, [_tx("ENGL 202W", is_writing=True)])
    assert _group(result, "GH")["satisfied"] is True
    assert _group(result, "Writing Across the Curriculum")["satisfied"] is True


# ── required baseline ────────────────────────────────────────────────────────

def test_required_course_done_and_missing():
    major = "Test Major, B.S."
    rows = [
        _req(program=major, group="Core", gtype="required", code="ETI 300"),
        _req(program=major, group="Core", gtype="required", code="ETI 301"),
    ]
    result = run_audit(rows, [_tx("ETI 300")])
    g = _group(result, "Core")
    assert g["done"] == 1
    assert g["missing"] == 1
    assert g["satisfied"] is False
    assert result["done"] == 1
    assert result["missing"] == 1
