"""
GET    /credential-choices                  — every course the caller has attested
PUT    /credential-choices                  — attest one course for one requirement
DELETE /credential-choices?program=&group=&course_code=  — take one back

The adviser-defined requirements in some PSU minors ("Select 6 credits from an
approved list in consultation with the minor adviser") have no course list to
evaluate, so the student names the courses they used.  See credential_choices.py for
the trust model; the short version is that this is the student's own claim, capped,
and limited to courses actually on their transcript so the credit total stays real.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from boto3.dynamodb.conditions import Key

import credential_catalog
import credential_choices as cc
from db import users_table, transcript_table
from deps import get_user_id

router = APIRouter()
logger = logging.getLogger(__name__)


class ChoiceBody(BaseModel):
    program:           str
    requirement_group: str
    course_code:       str


def _declared_or_404(user_id: str, program: str) -> dict:
    """The catalog entry for a credential the caller has actually declared."""
    user = users_table.get_item(Key={"user_id": user_id}).get("Item") or {}
    declared = {c.get("program") for c in (user.get("credentials") or [])}
    if program not in declared:
        raise HTTPException(
            status_code=400,
            detail="You haven't added that minor or certificate.",
        )
    entry = credential_catalog.get_credential(program)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown credential: {program}")
    return entry


def _adviser_group_or_400(entry: dict, group_name: str) -> dict:
    """Only an adviser-defined requirement can be filled this way.

    Every other group type is evaluated from the catalog, and letting a student
    hand-fill one would let them mark real requirements complete.
    """
    for g in entry.get("groups", []):
        if g["name"] == group_name and g["group_type"] == "unstructured_credits":
            return g
    raise HTTPException(
        status_code=400,
        detail="That requirement isn't one you choose courses for.",
    )


def _on_transcript(user_id: str, course_code: str) -> dict | None:
    """The student's own transcript row for a course, if they have one."""
    resp = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(user_id) & Key("course_code").eq(course_code)
    )
    items = resp.get("Items", [])
    return items[0] if items else None


@router.get("")
def list_choices(user_id: str = Depends(get_user_id)):
    """Attested courses keyed by `program|requirement_group`."""
    return {"choices": cc.get_credential_choices(user_id)}


@router.put("")
def add_choice(body: ChoiceBody, user_id: str = Depends(get_user_id)):
    code = cc.norm_code(body.course_code)
    if not cc.is_valid_code(code):
        raise HTTPException(status_code=400, detail="Invalid course code.")

    entry = _declared_or_404(user_id, body.program)
    _adviser_group_or_400(entry, body.requirement_group)

    # Must be a course the student actually has. This is what keeps the credit
    # total honest — we count real earned credits, never a guess about a course
    # they might take. It also mirrors the substitution rule.
    if _on_transcript(user_id, code) is None:
        raise HTTPException(
            status_code=400,
            detail=f"{code} isn't on your transcript yet. You can add it here once it is.",
        )

    existing = cc.get_credential_choices(user_id)
    key = cc.group_key(body.program, body.requirement_group)
    if code in existing.get(key, []):
        return {"status": "ok", "choices": existing}     # idempotent
    if sum(len(v) for v in existing.values()) >= cc.MAX_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"You can confirm up to {cc.MAX_PER_USER} courses this way.",
        )

    # One course may only back one requirement, for the same reason a substitution
    # may only back one: otherwise a single course silently completes two.
    for other_key, courses in existing.items():
        if other_key != key and code in courses:
            raise HTTPException(
                status_code=400,
                detail=f"{code} is already counted toward another requirement.",
            )

    cc.add_course(user_id, body.program, body.requirement_group, code)
    return {"status": "ok", "choices": cc.get_credential_choices(user_id)}


@router.delete("")
def remove_choice(
    program: str = Query(...),
    requirement_group: str = Query(...),
    course_code: str = Query(...),
    user_id: str = Depends(get_user_id),
):
    cc.remove_course(user_id, program, requirement_group, cc.norm_code(course_code))
    return {"status": "ok", "choices": cc.get_credential_choices(user_id)}
