"""
GET    /substitutions                          — the caller's declared substitutions
GET    /substitutions/candidates?requirement_code=CHE 100
                                               — transcript courses that could fill it
PUT    /substitutions                          — declare "X counts for requirement Y"
DELETE /substitutions?requirement_code=CHE 100 — undo one

A substitution is a per-user course equivalence (see backend/substitutions.py for
the model and why it lives in the user_course_choices table).  The audit and
timeline query the store live on every request, so a declaration flows straight
through to the audit, gen-ed check, timeline, and home dashboard — the same way a
manual transcript edit does.
"""

import logging

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from boto3.dynamodb.conditions import Key as DKey

from db import transcript_table
from deps import get_user_id
import substitutions as subs

router = APIRouter()
logger = logging.getLogger(__name__)

# Which transcript rows may stand in for a requirement. Planned/manual
# in-progress classes count (the student is taking it now), graded history and
# transfer credit count; nothing else exists.
_USABLE_STATUSES = ("done", "in_progress", "transfer")


class SubstitutionBody(BaseModel):
    requirement_code:  str
    substitute_course: str


def _transcript_courses(user_id: str) -> list[dict]:
    resp = transcript_table.query(KeyConditionExpression=DKey("user_id").eq(user_id))
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.query(
            KeyConditionExpression=DKey("user_id").eq(user_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return [c for c in items if c.get("status") in _USABLE_STATUSES]


def _course_view(c: dict) -> dict:
    earned = float(c.get("credits_earned", 0) or 0)
    if earned == 0 and c.get("status") == "in_progress":
        earned = float(c.get("credits", 0) or 0)
    return {
        "course_code":  subs.norm_code(c.get("course_code", "")),
        "course_title": c.get("course_title", "") or "",
        "credits":      earned,
        "grade":        c.get("grade", "") or "",
        "term":         c.get("term", "") or "",
        "status":       c.get("status", "done"),
    }


@router.get("")
def list_subs(user_id: str = Depends(get_user_id)):
    return {"substitutions": subs.list_substitutions(user_id)}


@router.get("/candidates")
def list_candidates(
    requirement_code: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    """
    The student's own courses, offered as possible stand-ins for one requirement.

    Ordering is the whole point of the endpoint: a course the audit hasn't
    already credited anywhere ("unused") is far more likely to be the one the
    adviser accepted, so those float to the top. Used courses stay in the list —
    a genuinely double-counted approval is the adviser's call, not ours — but are
    flagged so the UI can say so.
    """
    req = subs.norm_code(requirement_code)
    if not subs.is_valid_code(req):
        raise HTTPException(status_code=400, detail="Invalid requirement code.")

    courses = _transcript_courses(user_id)
    if not courses:
        return {"requirement_code": req, "current": None, "candidates": []}

    used = _used_codes(user_id, courses)
    current = subs.get_substitutions(user_id).get(req)

    views = [_course_view(c) for c in courses]
    for v in views:
        v["already_used"] = v["course_code"] in used
        v["selected"] = current is not None and v["course_code"] == current

    # Unused first, then by term (most recent first), then code.
    views.sort(key=lambda v: (v["already_used"], _term_sort(v["term"]), v["course_code"]))
    return {"requirement_code": req, "current": current, "candidates": views}


_SEASON_ORDER = {"FA": 0, "SU": 1, "SP": 2}


def _term_sort(term: str) -> tuple:
    """Most recent term first; blank/transfer terms last."""
    parts = (term or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return (9999, 99)
    return (-int(parts[1]), _SEASON_ORDER.get(parts[0], 99))


def _used_codes(user_id: str, courses: list[dict]) -> set[str]:
    """
    Course codes the major/gen-ed audit already credits. Best-effort: if the
    audit can't be run (no major set, catalog unreachable) every course is simply
    offered as unused rather than failing the picker.
    """
    try:
        from db import users_table
        from audit_engine import run_audit, run_gen_ed_audit
        from routers.audit import _filter_rows

        profile = users_table.get_item(Key={"user_id": user_id}).get("Item") or {}
        major = profile.get("major")
        if not major:
            return set()

        rows = _query_program(major)
        taken_codes = {subs.norm_code(c.get("course_code", "")) for c in courses}
        rows = _filter_rows(rows, profile.get("subplan"), taken_codes)
        declared = subs.get_substitutions(user_id)

        results = [run_audit(rows, courses, declared)]
        gen_ed_rows = _query_program("__GEN_ED__")
        if gen_ed_rows:
            results.append(run_gen_ed_audit(gen_ed_rows, courses, declared))

        used: set[str] = set()
        for res in results:
            for g in res.get("groups", []):
                for src in (g.get("sub_groups") or [g]):
                    for item in src.get("items", []):
                        if item.get("status") in ("done", "in_progress"):
                            used.add(subs.norm_code(item.get("course_code", "")))
        # A code the audit credits may be the *requirement's* code rather than
        # the transcript course's (equivalences, pairs) — intersect so the flag
        # only ever marks courses the student actually has.
        return used & {subs.norm_code(c.get("course_code", "")) for c in courses}
    except Exception:
        logger.warning("could not compute used codes for substitution picker", exc_info=True)
        return set()


def _query_program(program_name: str) -> list[dict]:
    from db import requirements_table

    resp = requirements_table.query(
        KeyConditionExpression=DKey("program_name").eq(program_name)
    )
    rows = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.query(
            KeyConditionExpression=DKey("program_name").eq(program_name),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        rows.extend(resp.get("Items", []))
    return rows


@router.put("")
def upsert_sub(body: SubstitutionBody, user_id: str = Depends(get_user_id)):
    req = subs.norm_code(body.requirement_code)
    sub = subs.norm_code(body.substitute_course)

    if not subs.is_valid_code(req):
        raise HTTPException(status_code=400, detail="Invalid requirement code.")
    if not subs.is_valid_code(sub):
        raise HTTPException(status_code=400, detail="Invalid course code.")
    if req == sub:
        raise HTTPException(
            status_code=400,
            detail="That's the same course — no substitution needed.",
        )

    # The substitute must be a course the student actually has. Without this a
    # student could declare any code and mark a requirement complete; with it,
    # a substitution can only ever re-point credit they already earned.
    have = {subs.norm_code(c.get("course_code", "")) for c in _transcript_courses(user_id)}
    if sub not in have:
        raise HTTPException(
            status_code=400,
            detail=f"{sub} isn't on your transcript. Add it under your in-progress "
                   "semester first, or upload an updated transcript.",
        )

    existing = subs.get_substitutions(user_id)
    if req not in existing and len(existing) >= subs.MAX_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"You can declare up to {subs.MAX_PER_USER} substitutions. "
                   "Remove one first, or contact support if your plan really needs more.",
        )
    # One course, one requirement — letting a single class cover two requirements
    # is the kind of double-count an adviser would reject, and it would silently
    # inflate the audit.
    for other_req, other_sub in existing.items():
        if other_sub == sub and other_req != req:
            raise HTTPException(
                status_code=400,
                detail=f"{sub} is already counting for {other_req}. "
                       "Remove that first if you meant to move it.",
            )

    try:
        subs.put_substitution(user_id, req, sub)
    except Exception:
        logger.warning("failed to persist substitution", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Couldn't save that right now — try again shortly.",
        )
    return {"status": "ok", "requirement_code": req, "substitute_course": sub}


@router.delete("")
def delete_sub(
    requirement_code: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    req = subs.norm_code(requirement_code)
    if not subs.is_valid_code(req):
        raise HTTPException(status_code=400, detail="Invalid requirement code.")
    try:
        subs.delete_substitution(user_id, req)
    except Exception:
        logger.warning("failed to clear substitution", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Couldn't update that right now — try again shortly.",
        )
    return {"status": "ok", "requirement_code": req}
