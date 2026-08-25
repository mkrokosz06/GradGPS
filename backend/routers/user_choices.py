"""
GET    /user-choices              — list the caller's class-selector decisions
PUT    /user-choices              — upsert one decision (which course fills a slot,
                                     and/or which term it's pinned to)
DELETE /user-choices?slot_key=... — clear one decision ("let GradGPS choose")

A decision is keyed by a stable requirement identity (slot_key) that the timeline
emits on each suggested slot, so the client echoes back the exact key it was given.
The timeline reads these rows to fix which course satisfies an option-bearing slot
and (best-effort) which semester it lands in. See docs / the plan for the slot_key
scheme (course:/one:/pool:/gened:).
"""

import re
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from boto3.dynamodb.conditions import Key as DKey

from db import user_choices_table
from deps import get_user_id

router = APIRouter()
logger = logging.getLogger(__name__)

_VALID_SLOT_KINDS = {"course", "choose_one", "pool", "gen_ed", "elective"}
_TERM_RE = re.compile(r"^(FA|SP|SU) \d{4}$")


class ChoiceBody(BaseModel):
    slot_key:      str
    slot_kind:     str
    chosen_course: str | None = None
    pinned_term:   str | None = None


def get_user_choices(user_id: str) -> dict[str, dict]:
    """
    Return the caller's stored decisions keyed by slot_key. DB-free callers
    (the timeline) use this to apply choices/pins. Values are plain dicts:
    {slot_kind, chosen_course?, pinned_term?}.
    """
    kwargs = {"KeyConditionExpression": DKey("user_id").eq(user_id)}
    resp = user_choices_table.query(**kwargs)
    items = list(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = user_choices_table.query(**kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return {
        it["slot_key"]: {
            "slot_kind":     it.get("slot_kind"),
            "chosen_course": it.get("chosen_course"),
            "pinned_term":   it.get("pinned_term"),
        }
        for it in items
    }


@router.get("")
def list_choices(user_id: str = Depends(get_user_id)):
    choices = get_user_choices(user_id)
    return {
        "choices": [
            {"slot_key": k, **v} for k, v in choices.items()
        ]
    }


@router.put("")
def upsert_choice(body: ChoiceBody, user_id: str = Depends(get_user_id)):
    slot_key = body.slot_key.strip()
    if not slot_key or "/" in slot_key:
        raise HTTPException(status_code=400, detail="Invalid slot_key.")
    if body.slot_kind not in _VALID_SLOT_KINDS:
        raise HTTPException(status_code=400, detail="Invalid slot_kind.")

    chosen = (body.chosen_course or "").strip() or None
    pinned = (body.pinned_term or "").strip() or None
    if pinned and not _TERM_RE.match(pinned):
        raise HTTPException(status_code=400, detail="Invalid pinned_term (expected e.g. 'FA 2026').")
    if not chosen and not pinned:
        # Nothing to store — clearing a decision is DELETE, not an empty PUT.
        raise HTTPException(status_code=400, detail="Provide chosen_course and/or pinned_term.")

    item = {
        "user_id":    user_id,
        "slot_key":   slot_key,
        "slot_kind":  body.slot_kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if chosen:
        item["chosen_course"] = chosen
    if pinned:
        item["pinned_term"] = pinned

    user_choices_table.put_item(Item=item)
    return {"status": "ok", "slot_key": slot_key}


@router.delete("")
def delete_choice(slot_key: str = Query(...), user_id: str = Depends(get_user_id)):
    key = slot_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Invalid slot_key.")
    user_choices_table.delete_item(Key={"user_id": user_id, "slot_key": key})
    return {"status": "ok", "slot_key": key}
