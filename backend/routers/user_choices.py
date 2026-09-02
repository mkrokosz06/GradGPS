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

# Reserved slot_key namespace owned by substitutions.py.
_SUB_PREFIX = "sub:"
# Reserved slot_key namespace owned by credential_choices.py — the courses a student
# attests to for an adviser-defined minor/certificate requirement.  Like `sub:`, these
# are a different kind of decision and must not leak into the timeline's choice/pin maps.
# Note the exact colon: a credential *slot* on the timeline is `credslot:<program>:…`
# and is an ordinary class-selector decision, so it is deliberately NOT reserved.
_CRED_PREFIX = "cred:"
_RESERVED_PREFIXES = (_SUB_PREFIX, _CRED_PREFIX)


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
    try:
        resp = user_choices_table.query(**kwargs)
        items = list(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = user_choices_table.query(**kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
            items.extend(resp.get("Items", []))
    except Exception:
        # The class-selector table may not exist / be IAM-granted yet in an env.
        # A missing table must NEVER break the timeline — degrade to "no choices".
        logger.warning("user_course_choices unavailable; treating as no choices", exc_info=True)
        return {}
    # Course substitutions share this table under a `sub:` slot_key namespace
    # (see substitutions.py) — they're a different kind of decision and must not
    # leak into the timeline's choice/pin maps.
    return {
        it["slot_key"]: {
            "slot_kind":     it.get("slot_kind"),
            "chosen_course": it.get("chosen_course"),
            "pinned_term":   it.get("pinned_term"),
        }
        for it in items
        if not str(it.get("slot_key", "")).startswith(_RESERVED_PREFIXES)
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
    if not slot_key or "/" in slot_key or slot_key.startswith(_RESERVED_PREFIXES):
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

    try:
        user_choices_table.put_item(Item=item)
    except Exception:
        logger.warning("failed to persist course choice", exc_info=True)
        raise HTTPException(status_code=503, detail="Couldn't save your choice right now — try again shortly.")
    return {"status": "ok", "slot_key": slot_key}


@router.delete("")
def delete_choice(slot_key: str = Query(...), user_id: str = Depends(get_user_id)):
    key = slot_key.strip()
    if not key or key.startswith(_RESERVED_PREFIXES):
        raise HTTPException(status_code=400, detail="Invalid slot_key.")
    try:
        user_choices_table.delete_item(Key={"user_id": user_id, "slot_key": key})
    except Exception:
        logger.warning("failed to clear course choice", exc_info=True)
        raise HTTPException(status_code=503, detail="Couldn't update your choice right now — try again shortly.")
    return {"status": "ok", "slot_key": key}
