"""
GET /audit
Returns the full degree audit for the authenticated user.
"""

from fastapi import APIRouter, HTTPException, Depends
from boto3.dynamodb.conditions import Key

from db import requirements_table, users_table, transcript_table
from audit_engine import run_audit, run_gen_ed_audit
from deps import get_user_id

GEN_ED_PROGRAM = "__GEN_ED__"

router = APIRouter()


def _filter_rows(rows: list[dict], subplan: str | None) -> list[dict]:
    """
    Filter requirement rows to only those relevant to the student's subplan.

    Three group categories exist in the scraped data:
      1. Common groups  — "Common Requirements for the Major (All Options)"
                          Always kept regardless of subplan.
      2. Real option groups — "Forensic Chemistry Option(20-22 credits)"
                              Kept when they match the student's subplan.
      3. Suggested-plan duplicates — "Forensic Chemistry Option: ...at University Park Campus"
                                     Semester-grid duplicates of the real groups. Always dropped.

    If no subplan is set, we drop only the suggested-plan duplicates (groups that
    contain " at " followed by a campus name) to avoid double-counting.
    """
    filtered = []
    subplan_lower = subplan.lower() if subplan else None

    # Build a list of all subplan keywords found across ALL groups so we can
    # detect and exclude groups that belong to OTHER subplans.
    all_group_names = [r.get("requirement_group", "") for r in rows]

    for row in rows:
        group = row.get("requirement_group", "")
        gl    = group.lower()

        # ── Always drop suggested-plan duplicate groups ──
        # These contain " at university park", " at commonwealth", etc.
        if " at university park" in gl or " at commonwealth" in gl:
            continue
        # Also drop the "MATH 22" variant groups (alternate track for students
        # who took MATH 022 instead of MATH 140 — rare edge case for V1)
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
            # (Groups from other subplans are implicitly excluded)

    return filtered


@router.get("")
def get_audit(user_id: str = Depends(get_user_id)):
    # ── 1. Get user's selected major + subplan ────────────────────────────────
    user_resp = users_table.get_item(Key={"user_id": user_id})
    user = user_resp.get("Item")
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Complete onboarding first.")

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

    # ── 3. Filter to the correct subplan ──────────────────────────────────────
    requirement_rows = _filter_rows(requirement_rows, subplan)

    # ── 4. Fetch student's transcript courses ─────────────────────────────────
    tx_resp = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(user_id)
    )
    transcript_courses = tx_resp.get("Items", [])

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
    result = run_audit(requirement_rows, transcript_courses)
    result["subplan"] = subplan

    # Total credits earned across all transcript courses (done + transfer)
    result["transcript_credits"] = round(
        sum(float(c.get("credits_earned", 0)) for c in transcript_courses
            if c.get("status") in ("done", "transfer")),
        1,
    )

    if gen_ed_rows:
        gen_ed_result = run_gen_ed_audit(gen_ed_rows, transcript_courses)
        result["gen_ed"] = gen_ed_result
    else:
        result["gen_ed"] = None

    return result


@router.get("/subplans")
def get_subplans(major: str):
    """
    Returns the available subplans for a given major by inspecting the
    requirement group names in the catalog.

    Example: major="Forensic Science, B.S."
    Returns: ["Forensic Chemistry", "Forensic Molecular Biology"]
    """
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(major),
        ProjectionExpression="requirement_group",
    )
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(major),
            ProjectionExpression="requirement_group",
            ExclusiveStartKey=resp["LastEvaluatedKey"]
        )
        items.extend(resp.get("Items", []))

    import re

    subplans = set()

    # Group names that are NOT subplans — generic section headers used across
    # all programs. Any name that matches one of these words is skipped.
    skip_words = {
        "common", "all options", "university park", "commonwealth",
        "math 22", "general", "requirements", "core", "elective",
        "suggested", "curriculum",
    }

    for item in items:
        g  = item.get("requirement_group", "")
        gl = g.lower()

        # Skip campus-specific / suggested-plan duplicates
        if " at " in gl:
            continue
        # Skip generic section headers
        if any(w in gl for w in skip_words):
            continue

        # Extract the subplan name: take text before the first "(" or ":"
        name = re.split(r"[(:（]", g)[0].strip()
        # Remove trailing "Option" word to get just the subplan label
        name = re.sub(r"\s+option$", "", name, flags=re.IGNORECASE).strip()
        if name:
            subplans.add(name)

    return {"major": major, "subplans": sorted(subplans)}
