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
    _programs_cache = sorted(all_names)
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

    update_expr = "SET major = :m"
    expr_vals   = {":m": body.major}

    if body.subplan:
        update_expr += ", subplan = :s"
        expr_vals[":s"] = body.subplan

    users_table.update_item(
        Key={"user_id": user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_vals,
    )

    return {"status": "ok", "major": body.major, "subplan": body.subplan}
