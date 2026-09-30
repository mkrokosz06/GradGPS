"""
Schreyer Honors College — the student's declaration and the per-major thesis rules.

A student declares themselves a Schreyer Scholar on the Account page; it is stored
as `honors = {"program": "schreyer", "entry": <admit year>}` on the users row.
Absent = not an honors student, and every function here is then a no-op, so the
field is safe to ship to users who never set it. Design: docs/honors-plan.md.

The course-level honors handling (RCL counting as ENGL 15 / CAS 100, honors
suffixes) is in audit_engine.HONORS_FILLS and applies to everyone — it doesn't
depend on this declaration, because an honors course on a transcript is a fact.
"""

import copy

SCHREYER = "schreyer"

# Admit year decides which honors-credit requirements apply (SHC requirements page):
# first-year 21 (years 1-2, incl. RCL) + 14 (years 3-4); second-year 9 + 14;
# third-year 14.
SCHREYER_ENTRIES = ("first_year", "second_year", "third_year")


def schreyer(user: dict | None) -> dict | None:
    """The student's Schreyer declaration, or None."""
    h = (user or {}).get("honors")
    if isinstance(h, dict) and h.get("program") == SCHREYER:
        return h
    return None


# ── Thesis in place of major electives ───────────────────────────────────────
# Some departments let a Scholar's thesis credits stand in for major electives.
# Each rule swaps the first plan slot carrying `label` for the thesis course,
# keeping the plan's credit total. Only rules a department publishes go here.
THESIS_RULES: dict[str, dict] = {
    # "For students in the Schreyer Honors Program, five credits of senior thesis
    # and one credit of ME 493 may be substituted for: 3 credits of Engineering
    # Technical Elective (ETE) and 3 credits of General Technical Elective (GTE)."
    "Mechanical Engineering, B.S. (Engineering)": {
        "source": "https://www.me.psu.edu/students/undergraduate/curriculum-metechnicalelectivescoursedescriptions.aspx",
        "swaps": [
            ("Engineering Technical Elective (ETE)", {"type": "course", "code": "ME 494H", "credits": 5.0}),
            ("General Technical Elective (GTE)",     {"type": "course", "code": "ME 493",  "credits": 1.0}),
        ],
    },
}


def apply_thesis_rule(template: dict | None, user: dict | None) -> dict | None:
    """The plan template with the major's thesis swapped in for the electives it
    replaces — for a declared Scholar in a major with a published rule. Returns
    the template untouched otherwise (the shared cached object, never mutated)."""
    if not template or not schreyer(user):
        return template
    rule = THESIS_RULES.get(template.get("program_name", ""))
    if not rule:
        return template

    out = copy.deepcopy(template)
    for label, course in rule["swaps"]:
        for sem in out.get("semesters", []):
            slots = sem.get("slots", [])
            i = next((i for i, s in enumerate(slots) if s.get("label") == label), None)
            if i is not None:
                slots[i] = {**course, "honors_thesis": True}
                break
    return out
