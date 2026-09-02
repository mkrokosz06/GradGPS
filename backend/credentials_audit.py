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
from audit_engine import run_audit

logger = logging.getLogger(__name__)


def audit_declared_credentials(user: dict,
                               transcript_courses: list[dict],
                               substitutions: dict | None = None) -> list[dict]:
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
        audit = run_audit(rows, transcript_courses, substitutions)
        audit.update({
            "program":         meta["program_name"],
            "kind":            meta["kind"],
            "catalog_credits": meta["credits"],
            # Credits the bulletin defers to an adviser. Surfaced rather than hidden:
            # the app never claims an adviser-approved requirement is met on its own.
            "manual_credits":  meta["manual_credits"],
            "url":             meta["url"],
        })
        out.append(audit)
    return out
