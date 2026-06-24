"""
POST /users/create  — register a new user (name + email)
GET  /users/me      — fetch current user's profile
"""

import uuid
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db import users_table
from deps import get_user_id

router = APIRouter()


class CreateUserBody(BaseModel):
    name:  str
    email: str


@router.post("/create")
def create_user(body: CreateUserBody):
    """
    Create a new user record. Returns a stable user_id derived from the email
    so duplicate sign-ups for the same email are idempotent.
    """
    if not body.name.strip() or not body.email.strip():
        raise HTTPException(status_code=400, detail="Name and email are required.")

    # Derive a stable, URL-safe user_id from the email
    user_id = (
        body.email.lower()
        .strip()
        .replace("@", "-")
        .replace(".", "-")
        .replace("+", "-")
    )

    # Check if already exists
    existing = users_table.get_item(Key={"user_id": user_id}).get("Item")
    if existing:
        # Idempotent — return the existing record
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
