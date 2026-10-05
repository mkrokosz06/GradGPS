"""
Auditing a student's declared minors / certificates.

Shared by `routers/audit.py` (progress on the Account screen) and
`routers/timeline.py` (scheduling the remaining courses), so the two can never
disagree about what a credential still requires.

A credential audit is the *same* `run_audit()` over a different set of requirement
rows and the same transcript — the engine cannot tell a credential from a major.
Requirement rows come from the bundled catalog (`credential_catalog.py`), not the
`requirements` table.
"""

from __future__ import annotations

import logging

import credential_catalog
import credential_choices
from audit_engine import run_audit

logger = logging.getLogger(__name__)


def audit_declared_credentials(user: dict,
                               transcript_courses: list[dict],
                               substitutions: dict | None = None,
                               attested: dict[str, list[str]] | None = None) -> list[dict]:
    """Audit every credential the user has declared.

    Returns [] when none are declared — the no-op that keeps this feature additive
    for every existing student.

    A course may count toward both the major and a credential: PSU's double-count rule
    varies by department and isn't in the catalog, and enforcing one would silently pick
    which program loses the course. The UI labels the overlap instead.
    """
    out: list[dict] = []
    for declared in user.get("credentials", []) or []:
        name = (declared or {}).get("program")
        loaded = credential_catalog.load_credential(name) if name else None
        if loaded is None:
            # A credential dropped by a catalog refresh must not break the whole
            # screen — the student's major matters more than a stale declaration.
            logger.warning("declared credential not in catalog: %s", name)
            continue
        meta, rows = loaded
        # Courses the student named for this credential's adviser-defined
        # requirements (credential_choices.py). Narrowed to this credential so the
        # engine never has to know which one it is auditing.
        by_group = credential_choices.for_credential(attested or {}, name)
        # Exclusive: one course fills one requirement inside a credential.
        audit = run_audit(rows, transcript_courses, substitutions, by_group, exclusive=True)
        if meta["ranges"]:
            _apply_total_gate(audit, meta["required_total"], meta["credits"].get("min") or 0,
                              meta["ranges"], meta["kind"])
        audit.update({
            "program":         meta["program_name"],
            "kind":            meta["kind"],
            "catalog_credits": meta["credits"],
            # Credits the bulletin defers to an adviser. Surfaced rather than hidden:
            # the app never claims an adviser-approved requirement is met on its own.
            "manual_credits":  meta["manual_credits"],
            "url":             meta["url"],
            # How many of those adviser-defined credits the student has confirmed,
            # so the UI can show progress rather than a permanent open item.
            "confirmed_credits": round(sum(
                g.get("credits_earned", 0) for g in audit["groups"]
                if g.get("group_type") == "unstructured_credits"), 1),
        })
        out.append(audit)
    return out


TOTAL_GROUP = "Total credits"


def _range_pools(audit: dict) -> list[dict]:
    """Every pool result (a whole group or a sub-group) with its catalog index."""
    out = []
    for g in audit["groups"]:
        for sg in (g.get("sub_groups") or [g]):
            idx = sg.get("pool_index", sg.get("pool_seq"))
            if idx is not None:
                out.append((int(idx), sg))
    return out


def _apply_total_gate(audit: dict, required: float, catalog_min: float,
                      ranges: dict[int, tuple[float, float]], kind: str = "credential") -> None:
    """How much of a credential's credit *ranges* is owed, checked against PSU's total.

    "Select 0-6 credits" pools satisfy at zero, so Ethics read as done at 9 of its
    18 credits. Its fixed requirements need 9 (the catalog minimum) and PSU says 18,
    so 9 credits are owed across the ranges: only credits a range pool counted above
    its own minimum go toward them. Everything else is already enforced per
    requirement by exclusive counting, and a credential-wide total would wrongly
    hold back a student whose variable-credit course ran below the catalog's guess.

    `ranges`: pool_seq -> (min, max) for each range pool. Adds a "Total credits"
    requirement, shaped as a departmental pool so the timeline schedules it."""
    # Never more than the ranges can hold: Turfgrass (Advanced) states 30 against a
    # 27 minimum, but its one range has 1 credit of room.
    room = sum(hi - lo for lo, hi in ranges.values())
    owed = round(min(required - catalog_min, room), 1)
    if owed <= 0 or not ranges:
        return
    extra = extra_ip = 0.0
    for idx, sg in _range_pools(audit):
        lo_hi = ranges.get(idx)
        if not lo_hi:
            continue
        lo, hi = lo_hi
        done = float(sg.get("credits_counted") or 0)
        both = done + float(sg.get("credits_counted_in_progress") or 0)
        extra += max(0.0, min(done, hi) - lo)
        extra_ip += max(0.0, min(both, hi) - lo)
    short = round(owed - extra, 1)
    if short <= 0:
        return
    status_ip = extra_ip >= owed
    audit["groups"].append({
        "name":           TOTAL_GROUP,
        "group_type":     "dept_credits",
        "threshold":      owed,
        "satisfied":      False,
        "done":           0,
        "in_progress":    1 if status_ip else 0,
        "missing":        0 if status_ip else 1,
        "credits_earned": round(extra, 1),
        "credits_needed": round(owed - extra_ip, 1) if not status_ip else 0,
        "items":          [],
        # No number in the wording: the timeline splits this into 3-credit slots
        # and every slot shows it.
        "pool_text":      (f"Elective credits from this {kind}'s lists "
                           f"({required:g} credits in all)"),
    })
    audit["in_progress" if status_ip else "missing"] += 1
    audit["total"] += 1
