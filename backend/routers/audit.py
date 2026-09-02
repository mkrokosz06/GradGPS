"""
GET /audit
Returns the full degree audit for the authenticated user.
"""

import logging

from fastapi import APIRouter, HTTPException, Depends, Header
from boto3.dynamodb.conditions import Key

from db import requirements_table, users_table, transcript_table
from audit_engine import run_audit, run_gen_ed_audit
import credential_choices
from credentials_audit import audit_declared_credentials
from deps import get_user_id
from client_meta import touch_client_meta
from substitutions import get_substitutions

GEN_ED_PROGRAM = "__GEN_ED__"

router = APIRouter()
logger = logging.getLogger(__name__)


import re as _re

# Matches any " at <Word> Campus" / " at <Word> <Word> Campus" pattern.
# Catches all PSU branch campuses: University Park, Commonwealth, Harrisburg,
# Brandywine, DuBois, Erie, Fayette, Greater Allegheny, New Kensington,
# Schuylkill, Scranton, Shenango, York, World Campus, etc.
_CAMPUS_RE = _re.compile(r" at [\w\s]+ campus", _re.IGNORECASE)

# Identifies a named "option" group (e.g. "Forensic Chemistry Option (20 credits)")
# but not common/all-options groups.
_OPTION_RE = _re.compile(r"\boption\b", _re.IGNORECASE)


def _filter_rows(rows: list[dict], subplan: str | None,
                 taken_codes: set[str] | None = None) -> list[dict]:
    """
    Filter requirement rows to only those relevant to the student's subplan.

    Three group categories exist in the scraped data:
      1. Common groups  — "Common Requirements for the Major (All Options)"
                          Always kept regardless of subplan.
      2. Real option groups — "Forensic Chemistry Option(20-22 credits)"
                              Kept when they match the student's subplan.
      3. Suggested-plan duplicates — "Forensic Chemistry Option: ...at University Park Campus"
                                     Semester-grid duplicates of the real groups. Always dropped.

    If no subplan is set and multiple option groups exist, auto-selects the
    best-matching option based on transcript overlap (taken_codes) to prevent
    inflation from evaluating all options simultaneously.
    """
    filtered = []
    subplan_lower = subplan.lower() if subplan else None

    for row in rows:
        group = row.get("requirement_group", "")
        gl    = group.lower()

        # ── Always drop campus-specific suggested-plan duplicate groups ──
        if _CAMPUS_RE.search(gl):
            continue
        if "suggested academic plan" in gl:
            continue
        if "math 22" in gl:
            continue

        # ── Always keep common / shared requirements ──
        if "common" in gl or "all options" in gl:
            filtered.append(row)
            continue

        # ── No subplan selected: keep remaining groups ──
        if not subplan_lower:
            filtered.append(row)
            continue

        # ── Subplan selected: keep only groups that match it ──
        if subplan_lower in gl:
            filtered.append(row)

    # Defensive fallback: if the subplan matched zero requirement groups
    if subplan_lower and not filtered:
        return _filter_rows(rows, None, taken_codes)

    # ── Auto-select best option when no subplan set ──────────────────────────
    # Programs with multiple named options (83+ programs like Biology, Integrative
    # Science, Criminology) inflate done/credits counts when all options are
    # evaluated simultaneously — the same course appears as "done" in every option.
    # Pick the single option where the student has completed the most courses.
    if not subplan_lower:
        filtered = _pick_best_option(filtered, taken_codes or set())

    return filtered


def _pick_best_option(rows: list[dict], taken_codes: set[str]) -> list[dict]:
    """
    If rows contain multiple named option groups, keep only the best-matching one.
    Non-option rows (common/required groups) are always kept unchanged.
    """
    from collections import defaultdict

    option_groups: dict[str, list[dict]] = defaultdict(list)
    non_option: list[dict] = []

    for row in rows:
        g  = row.get("requirement_group", "")
        gl = g.lower()
        # A "real" option group has "option" in name but is not a common/all-options group
        if _OPTION_RE.search(gl) and "all options" not in gl and "common" not in gl:
            option_groups[g].append(row)
        else:
            non_option.append(row)

    if len(option_groups) <= 1:
        return rows  # nothing to collapse

    # Score each option by how many of its course codes appear in the transcript
    best_option = max(
        option_groups,
        key=lambda g: sum(
            1 for r in option_groups[g]
            if r.get("course_code", "").strip().upper() in taken_codes
        ),
    )

    return non_option + option_groups[best_option]


@router.get("")
def get_audit(
    user_id: str = Depends(get_user_id),
    x_app_version: str | None = Header(None, alias="x-app-version"),
):
    # ── 1. Get user's selected major + subplan ────────────────────────────────
    user_resp = users_table.get_item(Key={"user_id": user_id})
    user = user_resp.get("Item")
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Complete onboarding first.")

    # Record which app build this user is on (throttled; the home screen hits
    # this endpoint on every launch). `user` is already in hand, so no extra read.
    touch_client_meta(user_id, user, x_app_version)

    major   = user.get("major")
    subplan = user.get("subplan")

    if not major:
        raise HTTPException(status_code=400, detail="No major selected. Pick your major first.")

    # ── 2. Fetch all requirement rows for this major ───────────────────────────
    req_resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(major)
    )
    requirement_rows = req_resp.get("Items", [])

    while "LastEvaluatedKey" in req_resp:
        req_resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(major),
            ExclusiveStartKey=req_resp["LastEvaluatedKey"]
        )
        requirement_rows.extend(req_resp.get("Items", []))

    if not requirement_rows:
        raise HTTPException(status_code=404, detail=f"No requirements found for major: {major}")

    # ── 3. Fetch student's transcript courses ─────────────────────────────────
    tx_resp = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(user_id)
    )
    transcript_courses = tx_resp.get("Items", [])

    # ── 4. Filter to the correct subplan ──────────────────────────────────────
    # Pass taken_codes so _filter_rows can auto-select the best option group
    # when the student hasn't explicitly chosen a subplan (prevents inflation
    # from 83+ multi-option programs counting the same courses multiple times).
    taken_codes = {c.get("course_code", "").strip().upper() for c in transcript_courses}
    requirement_rows = _filter_rows(requirement_rows, subplan, taken_codes)

    # ── 5. Fetch gen ed requirements ──────────────────────────────────────────
    gen_ed_resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(GEN_ED_PROGRAM)
    )
    gen_ed_rows = gen_ed_resp.get("Items", [])
    while "LastEvaluatedKey" in gen_ed_resp:
        gen_ed_resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(GEN_ED_PROGRAM),
            ExclusiveStartKey=gen_ed_resp["LastEvaluatedKey"]
        )
        gen_ed_rows.extend(gen_ed_resp.get("Items", []))

    # ── 6. Run audits ─────────────────────────────────────────────────────────
    # Student-declared course substitutions ("my ESC 120 counts for CHE 100") are
    # per-user equivalences folded into the taken-set — see substitutions.py.
    declared_subs = get_substitutions(user_id)

    result = run_audit(requirement_rows, transcript_courses, declared_subs)
    result["major"]   = major    # always use the stored value, not run_audit's fallback
    result["subplan"] = subplan

    # Total credits earned across all transcript courses (done + transfer)
    result["transcript_credits"] = round(
        sum(float(c.get("credits_earned", 0)) for c in transcript_courses
            if c.get("status") in ("done", "transfer")),
        1,
    )

    if gen_ed_rows:
        gen_ed_result = run_gen_ed_audit(gen_ed_rows, transcript_courses, declared_subs)
        result["gen_ed"] = gen_ed_result
    else:
        result["gen_ed"] = None

    # ── 7. Declared minors / certificates ─────────────────────────────────────
    # One extra audit per credential, over the SAME transcript and the SAME declared
    # substitutions — `run_audit()` is pure, so a credential is just a different set of
    # requirement rows (credential_catalog.py, a bundled file rather than the table).
    # A course may count toward both the major and a credential: PSU's double-count rule
    # varies by department and isn't in the catalog, and the alternative would silently
    # pick which program loses the course. The UI labels it instead.
    result["credentials"] = audit_declared_credentials(
        user, transcript_courses, declared_subs,
        credential_choices.get_credential_choices(user_id))

    return result
