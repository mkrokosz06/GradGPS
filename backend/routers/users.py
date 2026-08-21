"""
POST   /users/me     — authenticated upsert of the caller's profile
GET    /users/me     — fetch current user's profile
DELETE /users/me     — permanently delete the caller's account + all data
POST   /users/create — LEGACY, dev-bypass only (email-derived ids); removed
                       once the mobile app signs in with Google/Apple.
"""

import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import users_table, transcript_table, sessions_table, get_s3
from deps import get_current_user, get_user_id

router = APIRouter()
logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "degreecheck-transcripts")


class ProfileBody(BaseModel):
    # Optional fallbacks for identities whose token carries no name/email
    # (Apple only sends the name on FIRST sign-in, client-side; dev bypass
    # has no token at all).
    name:  str | None = None
    email: str | None = None


@router.post("/me")
def upsert_me(body: ProfileBody, user: dict = Depends(get_current_user)):
    """
    Create-or-update the caller's profile. Identity comes from the verified
    token (or dev bypass) — never from the request body. Verified token
    claims win over body values so a client can't overwrite its own verified
    email with an arbitrary one.
    """
    user_id = user["user_id"]
    email   = (user.get("email") or (body.email or "").strip().lower()) or None
    name    = (user.get("name")  or (body.name  or "").strip()) or None

    existing = users_table.get_item(Key={"user_id": user_id}).get("Item")

    update_fields = {}
    if name:
        update_fields["name"] = name
    if email:
        update_fields["email"] = email
    if user.get("provider") and user["provider"] != "dev":
        update_fields["provider"] = user["provider"]

    if existing:
        if update_fields:
            expr = "SET " + ", ".join(f"#{k} = :{k}" for k in update_fields)
            users_table.update_item(
                Key={"user_id": user_id},
                UpdateExpression=expr,
                ExpressionAttributeNames={f"#{k}": k for k in update_fields},
                ExpressionAttributeValues={f":{k}": v for k, v in update_fields.items()},
            )
        merged = {**existing, **update_fields}
    else:
        merged = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **update_fields,
        }
        users_table.put_item(Item=merged)

    return {
        "user_id": user_id,
        "name":    merged.get("name", ""),
        "email":   merged.get("email", ""),
        "is_new":  existing is None,
    }


@router.get("/me")
def get_me(user_id: str = Depends(get_user_id)):
    user = users_table.get_item(Key={"user_id": user_id}).get("Item")
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "user_id": user["user_id"],
        "name":    user.get("name", ""),
        "email":   user.get("email", ""),
        "major":   user.get("major"),
        "subplan": user.get("subplan"),
    }


@router.delete("/me")
def delete_me(user_id: str = Depends(get_user_id)):
    """
    Permanently delete the caller's account: stored transcript PDF, parsed
    course rows, profile record, and every active session. In-app account
    deletion is required by App Store guideline 5.1.1(v) and promised in the
    Privacy Policy.
    """
    from boto3.dynamodb.conditions import Key as DKey, Attr

    # Defense in depth (mirrors DELETE /transcript): the S3 key is built from
    # user_id and must never traverse outside the user's prefix.
    if "/" in user_id or ".." in user_id:
        raise HTTPException(status_code=400, detail="Invalid user id.")

    # 1. Stored PDF FIRST — if object storage is unreachable we must not
    #    report success, so fail loudly with everything else intact and let
    #    the user retry cleanly. delete_object is idempotent (no error when
    #    no PDF was ever stored).
    try:
        get_s3().delete_object(Bucket=S3_BUCKET, Key=f"transcripts/{user_id}/transcript.pdf")
    except Exception:
        logger.exception("S3 delete failed during account deletion for user_id=%s", user_id)
        raise HTTPException(
            status_code=502,
            detail="Could not delete your stored data. Please try again.",
        )

    # 2. Parsed transcript course rows (paginated).
    query_kwargs = {
        "KeyConditionExpression": DKey("user_id").eq(user_id),
        "ProjectionExpression": "user_id, course_code",
    }
    resp = transcript_table.query(**query_kwargs)
    rows = list(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.query(**query_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        rows.extend(resp.get("Items", []))
    if rows:
        with transcript_table.batch_writer() as batch:
            for item in rows:
                batch.delete_item(Key={"user_id": item["user_id"], "course_code": item["course_code"]})

    # 3. Profile record.
    users_table.delete_item(Key={"user_id": user_id})

    # 4. Sessions last, best-effort: the account data is already gone, so a
    #    failure here must not surface as an error. The sessions table is
    #    keyed by token hash with no user index, so scan-and-delete; any
    #    stragglers only resolve to a profile-less identity and expire via
    #    TTL within 30 days.
    try:
        scan_kwargs = {
            "FilterExpression": Attr("user_id").eq(user_id),
            "ProjectionExpression": "token_hash",
        }
        resp = sessions_table.scan(**scan_kwargs)
        hashes = [item["token_hash"] for item in resp.get("Items", [])]
        while "LastEvaluatedKey" in resp:
            resp = sessions_table.scan(**scan_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
            hashes.extend(item["token_hash"] for item in resp.get("Items", []))
        for token_hash in hashes:
            sessions_table.delete_item(Key={"token_hash": token_hash})
    except Exception:
        logger.exception("Session cleanup failed during account deletion for user_id=%s", user_id)

    return {"status": "ok"}


# ─── LEGACY (dev bypass only) ────────────────────────────────────────────────

class CreateUserBody(BaseModel):
    name:  str
    email: str


@router.post("/create")
def create_user(body: CreateUserBody):
    """
    LEGACY email-derived user creation for the current dev onboarding flow.
    Only reachable when AUTH_DEV_BYPASS=1; returns 410 otherwise. Delete this
    endpoint when the mobile app switches to Google/Apple sign-in.
    """
    if os.getenv("AUTH_DEV_BYPASS", "").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=410, detail="Sign in with Google or Apple instead.")

    if not body.name.strip() or not body.email.strip():
        raise HTTPException(status_code=400, detail="Name and email are required.")

    user_id = (
        body.email.lower()
        .strip()
        .replace("@", "-")
        .replace(".", "-")
        .replace("+", "-")
    )

    existing = users_table.get_item(Key={"user_id": user_id}).get("Item")
    if existing:
        return {
            "user_id": user_id,
            "name":    existing.get("name", body.name),
            "email":   existing.get("email", body.email),
            "is_new":  False,
        }

    users_table.put_item(Item={
        "user_id":    user_id,
        "name":       body.name.strip(),
        "email":      body.email.strip().lower(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "user_id": user_id,
        "name":    body.name.strip(),
        "email":   body.email.strip().lower(),
        "is_new":  True,
    }
