"""
The `dept_credits` group type — a departmental credit pool.

Most PSU minors are "a few prescribed courses, then N credits in the subject":

    Select 11 credits (at least 6 credits at the 400 level) in PSYCH
    Select 3 credits from any ANTH course except ANTH 1
    Select 6 credits from the ANTH 400-489 range
    Select 3-6 credits at the 400 level from ACCTG, BA, BLAW, … or STAT

None of these can be expressed as a course list, so no existing `group_type` fits:
`choose_credits` needs enumerated rows.  This is a *rule over the catalog*, evaluated
against the transcript — structurally the same idea as `_eval_writing_intensive()`
(audit_engine.py:1234), which evaluates the W/M/X/Y designation rather than a list.

`evaluate()` returns exactly the shape `_eval_choose_credits()` returns, so every
existing consumer (`_pool_counts`, the timeline's `_collect_missing`, the mobile UI)
keeps working unchanged.

Wiring this into the engine is three lines — see WIRING at the bottom of this file.
It is deliberately left out of `backend/audit_engine.py` for now: this tranche is the
data repair, and nothing declares a credential yet.
"""

from __future__ import annotations

import re

_CODE_RE = re.compile(r"^([A-Z]{2,6})\s*(\d{1,3})([A-Z]*)$")


def split_code(code: str) -> tuple[str, int, str] | None:
    """"PSYCH 301W" -> ("PSYCH", 301, "W").  None if it isn't a course code."""
    m = _CODE_RE.match(re.sub(r"\s+", " ", (code or "").strip().upper()))
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(3)


def matches(code: str, spec: dict) -> bool:
    """Whether a transcript course falls inside this departmental pool."""
    parsed = split_code(code)
    if not parsed:
        return False
    dept, number, _suffix = parsed

    subjects = set(spec.get("depts") or ([spec["dept"]] if spec.get("dept") else []))
    if subjects and dept not in subjects:
        return False

    if spec.get("min_level") is not None and number < spec["min_level"]:
        return False
    if spec.get("max_level") is not None and number > spec["max_level"]:
        return False

    excluded = {re.sub(r"\s+", " ", c.strip().upper()) for c in spec.get("exclude", [])}
    if excluded:
        norm = f"{dept} {number}"
        # Compare on the suffix-stripped code: "except ANTH 1" excludes ANTH 1N too.
        if norm in {c if " " in c else c for c in excluded} or code.strip().upper() in excluded:
            return False
        if any(split_code(c) and split_code(c)[:2] == (dept, number) for c in excluded):
            return False

    return True


def evaluate(spec: dict, taken: dict, threshold, consumed: set[str] | None = None) -> dict:
    """Evaluate a departmental pool against the taken-set.

    `taken` is `audit_engine._build_taken()` output: course_code -> {status, grade,
    credits_earned, …}.  It contains alias keys (CRIMJ 100 and CRIM 100 point at the
    *same* dict), so entries are de-duplicated by identity the way
    `_eval_writing_intensive` does — otherwise an aliased course counts twice.

    `consumed` mirrors the gen-ed exclusive path: codes already spent elsewhere are
    skipped, and codes used here are added to it.
    """
    thr = float(threshold) if threshold else 0.0
    seen: set[int] = set()
    credits_earned = credits_in_progress = 0.0
    level_credits = 0.0          # credits satisfying the "at least N at the L level" rule
    done = ip = 0
    items: list[dict] = []

    sub_level   = spec.get("sub_level")
    sub_credits = float(spec.get("sub_credits") or 0)

    for code, entry in sorted(taken.items()):
        if id(entry) in seen or not matches(code, spec):
            continue
        if consumed is not None and code in consumed:
            continue
        seen.add(id(entry))

        status = entry.get("status", "done")
        cr     = float(entry.get("credits_earned", 0) or 0) or 3.0

        if status == "done":
            credits_earned += cr
            done += 1
            parsed = split_code(code)
            if sub_level and parsed and parsed[1] >= sub_level:
                level_credits += cr
        elif status == "in_progress":
            credits_in_progress += cr
            ip += 1
        else:
            continue

        if consumed is not None:
            consumed.add(code)

        items.append({
            "course_code":  code,
            "course_title": entry.get("course_title", ""),
            "credits":      cr,
            "status":       status,
            "grade":        entry.get("grade", ""),
        })

    credits_needed = max(0.0, thr - credits_earned)
    satisfied = credits_earned >= thr if thr else True
    # The sub-constraint ("at least 6 credits at the 400 level") gates satisfaction too:
    # 11 credits of 100-level PSYCH does not complete the Psychology minor.
    if satisfied and sub_credits and level_credits < sub_credits:
        satisfied = False
        credits_needed = max(credits_needed, sub_credits - level_credits)

    return {
        "satisfied":           satisfied,
        "credits_earned":      round(min(credits_earned, thr) if thr else credits_earned, 1),
        "credits_in_progress": round(credits_in_progress, 1),
        "credits_needed":      round(credits_needed, 1),
        "threshold":           threshold,
        "done":                done,
        "in_progress":         ip,
        "missing":             0 if satisfied else 1,
        "items":               items,
        # Carried through for the UI: "Choose 8 more credits in PSYCH".
        "pool_spec":           spec,
    }


# ── WIRING (Phase 2, when credentials are actually audited) ──────────────────
#
# backend/audit_engine.py
#   1. `_eval_type()` (:1504) and `_eval_type_with_consumed()` (:1308):
#          elif gtype == "dept_credits":
#              return dept_credits.evaluate(_pool_spec(rows), taken, threshold, consumed)
#      where `_pool_spec(rows)` reads the spec off the group's single sentinel row
#      (course_code "__DEPT_<SUBJ>__", attributes dept/depts/min_level/…).
#   2. `_pool_counts()` (:1215): add "dept_credits" to the pool tuple so the group
#      counts as ONE requirement slot rather than one per matched course.
#
# backend/routers/timeline.py
#   3. `_collect_missing()` (:171): a `dept_credits` branch beside the choose_credits
#      one, emitting `is_pool: True` with no `pool_courses` (there is no list to show)
#      and a title from `pool_spec["text"]`.
