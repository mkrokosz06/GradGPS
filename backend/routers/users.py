"""
POST /users/me      — authenticated upsert of the caller's profile
GET  /users/me      — fetch current user's profile
POST /users/create  — LEGACY, dev-bypass only (email-derived ids); removed
                      once the mobile app signs in with Google/Apple.
"""

import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import users_table
from deps import get_current_user, get_user_id

router = APIRouter()


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
        merged = {"user_id": user_id, **update_fields}
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
        "user_id": user_id,
        "name":    body.name.strip(),
        "email":   body.email.strip().lower(),
    })

    return {
        "user_id": user_id,
        "name":    body.name.strip(),
        "email":   body.email.strip().lower(),
        "is_new":  True,
    }
