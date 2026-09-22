"""
Entrance to Major — the gate a student must clear to be admitted to their major.

This is deliberately NOT a set of requirement rows. Every course PSU names in an
Entrance to Major section is already a requirement of the major, so storing them
as requirements would double-count the credits and schedule the same course
twice. What the gate adds is ordering and urgency: these particular courses have
a deadline (PSU expects them by the end of the fourth semester), usually carry a
minimum grade of C, and sit behind a GPA floor.

So the audit reports gate PROGRESS, and the timeline uses the gate to decide
what to schedule first. Nothing here changes what a degree requires.

Reads the bundled `entrance_data/entrance_requirements.json` (see
scripts/scrape_entrance_to_major.py) — same pattern as credential_catalog.

`status` is never "met" when the bulletin states a condition we cannot check
(a portfolio, volunteer hours, an application deadline, contradictory GPA
figures). Those return "needs_confirmation" with PSU's own wording attached.
Telling a student they have cleared a gate they have not is the failure that
matters; the reverse only costs them a conversation with an adviser.
"""

import json
import logging
import os
import re

from audit_engine import _build_taken, _grade_meets

logger = logging.getLogger(__name__)

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "entrance_data", "entrance_requirements.json")

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(_DATA_PATH, encoding="utf-8") as fh:
                _cache = json.load(fh).get("programs", {})
        except Exception:
            # An unreadable data file degrades to "no gate known", never a 500.
            logger.warning("entrance_requirements.json unavailable", exc_info=True)
            _cache = {}
    return _cache


def get_spec(program_name: str) -> dict | None:
    return _load().get((program_name or "").strip())


def has_gate(program_name: str) -> bool:
    spec = get_spec(program_name)
    return bool(spec and (spec.get("groups") or spec.get("gpa_min")
                          or spec.get("semester_standing")))


def _branch_status(branch: list[str], taken: dict, min_grade: str) -> str:
    """A branch is every course in it — "ACCTG 201 and ACCTG 202" is not half
    satisfied by ACCTG 201. Mirrors the audit engine's compound-branch rule:
    `partial` never counts as done."""
    states = []
    for code in branch:
        entry = taken.get(code.strip().upper())
        if not entry:
            states.append("missing")
        elif entry.get("status") == "in_progress":
            states.append("in_progress")
        elif _grade_meets(entry.get("grade", ""), min_grade):
            states.append("done")
        else:
            # Took it, but not at the grade the gate demands.
            states.append("below_grade")
    if all(s == "done" for s in states):
        return "done"
    if any(s == "below_grade" for s in states):
        return "below_grade"
    if all(s in ("done", "in_progress") for s in states):
        return "in_progress"
    if any(s in ("done", "in_progress") for s in states):
        return "partial"
    return "missing"


def evaluate(program_name: str, transcript_courses: list[dict],
             substitutions: dict | None = None) -> dict | None:
    """Gate progress for one student. None when the program has no gate."""
    spec = get_spec(program_name)
    if not spec:
        return None

    taken = _build_taken(transcript_courses, substitutions)
    min_grade = spec.get("min_grade") or ""

    groups = []
    for group in spec.get("groups", []):
        branches = [{"codes": b, "status": _branch_status(b, taken, min_grade)}
                    for b in group]
        best = "missing"
        for order in ("done", "in_progress", "below_grade", "partial"):
            if any(b["status"] == order for b in branches):
                best = order
                break
        groups.append({
            "branches": branches,
            "status": best,
            # Flattened for clients that just want to list the options.
            "options": [c for b in group for c in b],
        })

    done = sum(1 for g in groups if g["status"] == "done")
    in_progress = sum(1 for g in groups if g["status"] == "in_progress")
    remaining = [c for g in groups if g["status"] in ("missing", "partial", "below_grade")
                 for b in g["branches"] for c in b["codes"]]

    courses_cleared = bool(groups) and done == len(groups)
    if spec.get("has_unmodelled"):
        status = "needs_confirmation"
    elif not groups:
        # GPA / semester-standing only: nothing course-based to check.
        status = "no_course_requirements"
    elif courses_cleared:
        status = "courses_met"
    else:
        status = "in_progress" if (done or in_progress) else "not_started"

    return {
        "program": program_name,
        "status": status,
        "groups": groups,
        "groups_done": done,
        "groups_total": len(groups),
        "remaining_courses": sorted(set(remaining)),
        "gpa_min": spec.get("gpa_min"),
        "gpa_candidates": spec.get("gpa_candidates") or [],
        "min_grade": spec.get("min_grade"),
        "semester_standing": spec.get("semester_standing"),
        "needs_confirmation": bool(spec.get("has_unmodelled")),
        "notes": spec.get("notes") or [],
        "source_url": spec.get("source_url"),
    }


def priority_codes(program_name: str) -> set[str]:
    """Every course that can help clear the gate.

    The timeline uses this to schedule gate courses first. It is a set of
    candidates, not a plan: which one the student takes is still decided by the
    audit and the SAP template.
    """
    spec = get_spec(program_name)
    if not spec:
        return set()
    return {c.strip().upper() for g in spec.get("groups", []) for b in g for c in b}

def attach_slots(gate: dict | None, slots: list[dict]) -> dict | None:
    """Give each unmet gate group the timeline slot that can satisfy it.

    The checklist lets a student choose WHICH course clears a group, and
    optionally which semester it lands in. Both are stored as an ordinary
    `user_course_choices` row — the same `slot_key` / `chosen_course` /
    `pinned_term` the pool dropdown already writes.

    Reusing the existing slot is the whole point. Every gate course is already a
    requirement of the major, so a gate-specific slot of its own would put a
    second copy of the course in the plan. Attaching the key the timeline
    already emits means the pick flows through the timeline, home dashboard and
    registration view with no extra wiring, and cannot double-schedule.

    `slots` must come from the BUILT timeline, not from `_collect_missing()`.
    The two disagree: a templated major's plan is emitted by `_reflow_template`,
    so ETI's first gate group is `one:CYBER 100|IST 110` there and
    `course:ETI 100` in the Layer 1 vocabulary. Attaching the latter would write
    a choice against a slot the student's timeline never renders, and the pick
    would silently do nothing.
    """
    if not gate:
        return gate

    def _base(code: str) -> str:
        return re.sub(r"[WHNMXY]$", "", (code or "").strip().upper()).strip()

    def _slot_codes(slot: dict) -> set[str]:
        codes = [o.get("course_code", "") for o in (slot.get("options") or [])]
        codes += re.split(r"\s+or\s+", slot.get("course_code") or "", flags=re.I)
        return {_base(c) for c in codes if _base(c)}

    usable = [(s, _slot_codes(s)) for s in slots if s.get("slot_key")]

    for group in gate.get("groups", []):
        if group.get("status") == "done":
            continue
        wanted = {_base(c) for c in group.get("options", [])}
        # Score by how much of the group a slot covers, and prefer one that
        # actually offers a choice. Taking the first code that matched anything
        # picked `course:ETI 100` — a single named slot — over the slot offering
        # all seven of that group's alternatives.
        best = None
        best_score = (0, 0)
        for slot, codes in usable:
            overlap = len(wanted & codes)
            if not overlap:
                continue
            score = (overlap, len(slot.get("options") or []))
            if score > best_score:
                best, best_score = slot, score
        if best is None:
            continue
        group["slot_key"] = best["slot_key"]
        group["slot_kind"] = best.get("slot_kind")
        # Only what this slot actually offers is pickable. A gate group can name
        # a course the major does not (Music Education's ENGL 15 lives in
        # gen-ed), and offering it would write a choice nothing reads.
        offered = [o.get("course_code", "") for o in (best.get("options") or [])]
        group["choosable"] = [c for c in group["options"]
                              if _base(c) in {_base(o) for o in offered}]
    return gate
