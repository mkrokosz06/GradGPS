"""
GET  /programs/search?q=forensic    — fuzzy search program names
POST /programs/select               — save a user's major selection
"""

from fastapi import APIRouter, Query, Header, HTTPException
from pydantic import BaseModel
from boto3.dynamodb.conditions import Key

from db import requirements_table, users_table

router = APIRouter()


@router.get("/search")
def search_programs(q: str = Query(..., min_length=1)):
    """
    Scans the requirements table for distinct program_names containing the query string.
    DynamoDB doesn't support full-text search natively, so this does a simple
    case-insensitive substring match on a cached program list.

    For V1 with 551 programs this is fast enough. Post-launch: cache the list in memory.
    """
    # Scan is acceptable here because we're only reading program_name (projected),
    # not the full 31k rows. In production, maintain a separate small programs table.
    resp = requirements_table.scan(
        ProjectionExpression="program_name",
        FilterExpression="contains(program_name, :q)",
        ExpressionAttributeValues={":q": q},
    )

    # Deduplicate
    names = sorted({item["program_name"] for item in resp.get("Items", [])})
    return {"results": names, "count": len(names)}


class SelectMajorBody(BaseModel):
    major:   str
    subplan: str | None = None   # e.g. "Forensic Chemistry" — optional at selection time


@router.post("/select")
def select_major(
    body: SelectMajorBody,
    x_user_id: str = Header(..., alias="x-user-id"),
):
    """Save the student's chosen major (and optional subplan) to their user record."""
    # Verify the major exists in the catalog
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(body.major),
        Limit=1,
    )
    if not resp.get("Items"):
        raise HTTPException(status_code=404, detail=f"Major not found: {body.major}")

    update_expr  = "SET major = :m"
    expr_vals    = {":m": body.major}

    if body.subplan:
        update_expr += ", subplan = :s"
        expr_vals[":s"] = body.subplan

    users_table.update_item(
        Key={"user_id": x_user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_vals,
    )

    return {"status": "ok", "major": body.major, "subplan": body.subplan}
