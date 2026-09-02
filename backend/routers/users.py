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
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

import credential_catalog
import credential_choices
from db import users_table, transcript_table, sessions_table, user_choices_table, get_s3
from deps import get_current_user, get_user_id
from client_meta import touch_client_meta

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
def upsert_me(
    body: ProfileBody,
    user: dict = Depends(get_current_user),
    x_app_version: str | None = Header(None, alias="x-app-version"),
):
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

    # Stamp the app build on the row (throttled). `existing` is the pre-update
    # record, so a version bump since last seen is detected correctly.
    touch_client_meta(user_id, existing, x_app_version)

    return {
        "user_id": user_id,
        "name":    merged.get("name", ""),
        "email":   merged.get("email", ""),
        "is_new":  existing is None,
    }


@router.get("/me")
def get_me(
    user_id: str = Depends(get_user_id),
    x_app_version: str | None = Header(None, alias="x-app-version"),
):
    user = users_table.get_item(Key={"user_id": user_id}).get("Item")
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    touch_client_meta(user_id, user, x_app_version)
    return {
        "user_id": user["user_id"],
        "name":    user.get("name", ""),
        "email":   user.get("email", ""),
        "major":   user.get("major"),
        "subplan": user.get("subplan"),
        # Declared minors / certificates. Strictly additive: an older mobile build
        # ignores the field, and an account that has declared none omits it entirely.
        "credentials": user.get("credentials", []),
    }


# A student may stack a couple of credentials, but not an unbounded list — the same
# reasoning as MAX_PER_USER in substitutions.py: it is a declaration about themselves,
# and an uncapped list makes the timeline meaningless.
MAX_CREDENTIALS = 3


class CredentialsBody(BaseModel):
    programs: list[str]


@router.put("/me/credentials")
def set_my_credentials(
    body: CredentialsBody,
    user_id: str = Depends(get_user_id),
):
    """Declare the caller's minors / certificates.

    Replaces the whole list rather than adding one at a time — idempotent, and there is
    no add/remove race for a client to lose. Declaring a credential never changes the
    major; it is additional coursework (see docs/minors-certificates.md).
    """
    seen: list[str] = []
    for name in body.programs:
        name = (name or "").strip()
        if not name or name in seen:
            continue
        if not credential_catalog.is_credential(name):
            raise HTTPException(
                status_code=400,
                detail=f"{name} is not a minor or certificate GradGPS supports.",
            )
        seen.append(name)

    if len(seen) > MAX_CREDENTIALS:
        raise HTTPException(
            status_code=400,
            detail=f"You can declare up to {MAX_CREDENTIALS} minors or certificates.",
        )

    user = users_table.get_item(Key={"user_id": user_id}).get("Item")
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.get("major") in seen:
        raise HTTPException(
            status_code=400,
            detail="That is already your major — pick a different minor or certificate.",
        )

    # Dropping a credential drops the courses the student attested for it — otherwise
    # re-adding it later would silently resurrect stale claims.
    for previous in (user.get("credentials") or []):
        if previous.get("program") and previous["program"] not in seen:
            credential_choices.remove_credential(user_id, previous["program"])

    credentials = [
        {"program": n, "kind": credential_catalog.get_credential(n)["kind"]}
        for n in seen
    ]
    if credentials:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET credentials = :c",
            ExpressionAttributeValues={":c": credentials},
        )
    else:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="REMOVE credentials",
        )
    return {"status": "ok", "credentials": credentials}


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

    # 3. Class-selector course choices / semester pins (paginated).
    choice_kwargs = {
        "KeyConditionExpression": DKey("user_id").eq(user_id),
        "ProjectionExpression": "user_id, slot_key",
    }
    resp = user_choices_table.query(**choice_kwargs)
    choices = list(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = user_choices_table.query(**choice_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        choices.extend(resp.get("Items", []))
    if choices:
        with user_choices_table.batch_writer() as batch:
            for item in choices:
                batch.delete_item(Key={"user_id": item["user_id"], "slot_key": item["slot_key"]})

    # 4. Profile record.
    users_table.delete_item(Key={"user_id": user_id})

    # 5. Sessions last, best-effort: the account data is already gone, so a
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
