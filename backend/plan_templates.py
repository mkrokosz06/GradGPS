"""
Suggested Academic Plan (SAP) templates — the ordered, prerequisite-sequenced,
credit-balanced backbone the timeline reflows a student's real state against.

A template is authored per University Park major from the published PSU bulletin
SAP (see docs/timeline-sap-hybrid.md).  Templates live as JSON under
`data/plan_templates/`; `load_template()` is the single entry point.  The audit
engine remains the source of truth for what a student has *satisfied* — a
template only supplies order, completeness, and credit balance.
"""

import json
import os
from functools import lru_cache

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sap_templates")

VALID_SLOT_TYPES = {"course", "choose_one", "gen_ed", "pool", "elective"}


@lru_cache(maxsize=1)
def _all_templates() -> list[dict]:
    """Load and cache every template JSON in the data directory."""
    templates: list[dict] = []
    if not os.path.isdir(_DIR):
        return templates
    for fname in sorted(os.listdir(_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(_DIR, fname), encoding="utf-8") as f:
            tpl = json.load(f)
            tpl["_file"] = fname
            templates.append(tpl)
    return templates


def load_template(program_name: str, subplan: str | None = None) -> dict | None:
    """Return the SAP template for a program (+ optional subplan), or None.

    Matches on `program_name`; prefers an exact `subplan` match but falls back to
    the subplan-less template for the program so a student who hasn't picked an
    option still gets the base plan.
    """
    candidates = [t for t in _all_templates() if t.get("program_name") == program_name]
    if not candidates:
        return None
    if subplan:
        exact = [t for t in candidates if t.get("subplan") == subplan]
        if exact:
            return exact[0]
    base = [t for t in candidates if not t.get("subplan")]
    return (base or candidates)[0]


def iter_slots(template: dict):
    """Yield (semester_index, semester, slot) for every slot, in plan order."""
    for si, sem in enumerate(template.get("semesters", [])):
        for slot in sem.get("slots", []):
            yield si, sem, slot


def slot_credits(slot: dict) -> float:
    """Credits a slot contributes."""
    return float(slot.get("credits", 3) or 3)


def validate_template(template: dict) -> list[str]:
    """Structural + grand-total credit checks.  Returns a list of problems
    (empty = valid).  Does NOT hit the catalog — that's a separate DB-backed
    check.

    Note: per-semester `credits` fields are treated as ADVISORY, not asserted.
    PSU bulletin SAPs are frequently internally inconsistent — a semester's
    stated total can disagree with its own listed line items (e.g. Accounting
    Year 1: listed 12/17 vs stated 15/14, which cancel to a correct 120 grand
    total). The engine schedules by slot credits and reflow rebalances, so only
    the grand total needs to be right.
    """
    problems: list[str] = []
    sems = template.get("semesters", [])
    if not sems:
        problems.append("no semesters")
        return problems

    grand = 0.0
    for si, sem in enumerate(sems):
        slots = sem.get("slots", [])
        if not slots:
            problems.append(f"semester {si}: no slots")
        grand += sum(slot_credits(s) for s in slots)
        for j, slot in enumerate(slots):
            t = slot.get("type")
            if t not in VALID_SLOT_TYPES:
                problems.append(f"semester {si} slot {j}: bad type {t!r}")
            if t == "course" and not slot.get("code"):
                problems.append(f"semester {si} slot {j}: course slot missing 'code'")
            if t == "choose_one" and not slot.get("codes"):
                problems.append(f"semester {si} slot {j}: choose_one missing 'codes'")

    total = float(template.get("total_credits", grand))
    if abs(grand - total) > 0.01:
        problems.append(f"grand total {grand} != declared total_credits {total}")
    return problems


def fixed_codes(template: dict) -> set[str]:
    """Every concrete course code the template pins (course + choose_one options
    + pool anchor codes) — used to check the template against the catalog."""
    codes: set[str] = set()
    for _, _, slot in iter_slots(template):
        if slot.get("code"):
            codes.add(slot["code"])
        for c in slot.get("codes", []):
            codes.add(c)
    return codes


def pinned_course_codes(template: dict) -> set[str]:
    """Only the single-course (`type: course`) codes the template hard-pins.

    Unlike fixed_codes(), this excludes choose_one alternatives — a choose_one is
    satisfied by ANY option, and SAPs routinely list gen-ed alternatives (CAS 100,
    ESL 15, …) that live in the gen-ed space rather than the major catalog, so
    requiring every alternative to exist would be wrong."""
    return {slot["code"] for _, _, slot in iter_slots(template)
            if slot.get("type") == "course" and slot.get("code")}
