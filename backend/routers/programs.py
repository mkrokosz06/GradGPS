"""
GET  /programs/all               — return all program names (cached in memory after first call)
GET  /programs/search?q=forensic — filter cached list, case-insensitive substring match
POST /programs/select            — save a user's major selection
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from boto3.dynamodb.conditions import Key

from db import requirements_table, users_table
from deps import get_user_id

router = APIRouter()

# ── University Park scoping ──────────────────────────────────────────────────
# This app is University Park (main campus) only.  Program names carry a
# parenthetical qualifier ONLY to disambiguate an offering that exists at more
# than one campus (e.g. "Accounting, B.S. (Business)" at UP vs
# "Accounting, B.S. (Capital)" at Harrisburg).  The large majority of programs
# have NO parenthetical at all and are UP by default — so this MUST stay a
# denylist of non-UP campuses, not an allowlist of UP colleges (an allowlist
# would wrongly drop every unqualified program).
#
# The campus list is kept EXHAUSTIVE — every Commonwealth/branch campus and its
# common aliases, not just the ones currently in the catalog — so a future
# re-scrape can't silently leak a campus we forgot to list.  `is_up_program()`
# is the single authoritative definition of "a University Park program"; the SAP
# scraper (see docs/timeline-sap-hybrid.md) imports it so the app and the
# template set agree on exactly which majors are in scope.
_NON_UP_CAMPUS_KEYWORDS = {
    "abington", "altoona", "beaver", "berks", "brandywine", "dubois", "du bois",
    "erie", "behrend", "fayette", "greater allegheny", "harrisburg", "capital",
    "hazleton", "lehigh valley", "mont alto", "new kensington", "schuylkill",
    "scranton", "worthington scranton", "shenango", "wilkes-barre", "york",
    "great valley", "university college", "world campus", "commonwealth",
}

# The resident-instruction colleges at University Park.  A parenthetical drawn
# from this set positively means UP.  Not used to filter (unqualified programs
# have no college either) — it's the authoritative allowlist the SAP scraper
# validates college paths against, and lets us assert a parenthetical is a known
# college rather than an unrecognised (possibly new-campus) surprise.
_UP_COLLEGE_QUALIFIERS = {
    "agricultural sciences", "arts and architecture", "business",
    "communications", "earth and mineral sciences", "education", "engineering",
    "health and human development", "information sciences and technology",
    "intercollege", "liberal arts", "nursing", "science", "k-12",
}


def is_up_program(name: str) -> bool:
    """Whether a program is offered at University Park (this app's only scope).

    Keeps every program EXCEPT those whose name carries a non-UP campus
    parenthetical.  Unqualified names (the majority) and UP-college
    parentheticals are kept; branch/Commonwealth/World Campus offerings are
    dropped.  This is the shared UP-scope definition used by both the program
    list and the SAP template pipeline.
    """
    nl = name.lower()
    return not any(
        f"({kw})" in nl or f"({kw} " in nl for kw in _NON_UP_CAMPUS_KEYWORDS
    )


# In-memory cache populated on first request — avoids a 10-page DynamoDB scan per search
_programs_cache: list[str] | None = None


def _load_all_programs() -> list[str]:
    global _programs_cache
    if _programs_cache is not None:
        return _programs_cache
    all_names: set[str] = set()
    scan_kwargs: dict = {"ProjectionExpression": "program_name"}
    while True:
        resp = requirements_table.scan(**scan_kwargs)
        all_names.update(item["program_name"] for item in resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        scan_kwargs["ExclusiveStartKey"] = last
    # Exclude __GEN_ED__ sentinel and non-University-Park programs
    _programs_cache = sorted(
        n for n in all_names
        if n != "__GEN_ED__" and is_up_program(n)
    )
    return _programs_cache


@router.get("/all")
def get_all_programs():
    """Return every distinct program name — used by the mobile app to populate the full list."""
    names = _load_all_programs()
    return {"results": names, "count": len(names)}


@router.get("/search")
def search_programs(q: str = Query(..., min_length=1)):
    """Case-insensitive substring search over the cached program list."""
    q_lower = q.lower()
    names = [n for n in _load_all_programs() if q_lower in n.lower()]
    return {"results": names, "count": len(names)}


class SelectMajorBody(BaseModel):
    major:   str
    subplan: str | None = None   # e.g. "Forensic Chemistry" — optional at selection time


@router.post("/select")
def select_major(
    body: SelectMajorBody,
    user_id: str = Depends(get_user_id),
):
    """Save the student's chosen major (and optional subplan) to their user record."""
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(body.major),
        Limit=1,
    )
    if not resp.get("Items"):
        raise HTTPException(status_code=404, detail=f"Major not found: {body.major}")

    # Validate subplan actually exists in the requirement groups for this major
    # before persisting it, so a stale subplan from a previous major can't leak.
    effective_subplan = None
    if body.subplan:
        all_rows_resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(body.major),
            ProjectionExpression="requirement_group",
        )
        all_group_names = {r.get("requirement_group", "").lower() for r in all_rows_resp.get("Items", [])}
        if any(body.subplan.lower() in g for g in all_group_names):
            effective_subplan = body.subplan

    if effective_subplan:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET major = :m, subplan = :s",
            ExpressionAttributeValues={":m": body.major, ":s": effective_subplan},
        )
    else:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET major = :m REMOVE subplan",
            ExpressionAttributeValues={":m": body.major},
        )

    return {"status": "ok", "major": body.major, "subplan": effective_subplan}
