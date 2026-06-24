"""
Shared FastAPI dependencies.
"""

from fastapi import Header, HTTPException


def get_user_id(x_user_id: str = Header(..., alias="x-user-id")) -> str:
    """Extract and return the authenticated user ID from the request header."""
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(status_code=401, detail="Missing x-user-id header.")
    return x_user_id
