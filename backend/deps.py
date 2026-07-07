"""
Shared FastAPI dependencies — authentication.

Real path:   Authorization: Bearer <Google/Apple ID token>  → verified,
             user_id = provider-scoped sub ("google:<sub>" / "apple:<sub>").

Dev bypass:  AUTH_DEV_BYPASS=1 in the environment lets the legacy x-user-id
             header through unverified, so local dev works without OAuth set
             up. NEVER enable in production — it is the old spoofable model.

user_id charset is enforced here at the choke point (also protects the S3
object key built from it — transcripts/<user_id>/transcript.pdf).
"""

import os
import re
import logging

from fastapi import Header, HTTPException

from auth import verify_id_token, TokenVerificationError

logger = logging.getLogger(__name__)

# Google subs are numeric; Apple subs look like "001234.a1b2c3.0987"; our
# prefix adds a colon; legacy dev ids use dashes. No slashes, no dots at the
# start, nothing S3/URL-hostile.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")


def _dev_bypass_enabled() -> bool:
    # Read at request time (not import time) so tests can toggle it.
    return os.getenv("AUTH_DEV_BYPASS", "").strip().lower() in {"1", "true", "yes"}


def get_current_user(
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None, alias="x-user-id"),
) -> dict:
    """
    Authenticate the request. Returns identity claims:
        {"user_id", "provider", "sub", "email", "email_verified", "name"}
    Dev-bypass identities return provider="dev" with only user_id populated.
    """
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="Invalid Authorization header. Expected: Bearer <token>.")
        try:
            claims = verify_id_token(token.strip())
        except TokenVerificationError as e:
            raise HTTPException(status_code=401, detail=str(e))
        if not _USER_ID_RE.match(claims["user_id"]):
            # Provider subs should always pass; belt-and-suspenders.
            logger.error("Verified sub failed charset check: %r", claims["user_id"])
            raise HTTPException(status_code=401, detail="Invalid token subject.")
        return claims

    if _dev_bypass_enabled() and x_user_id and x_user_id.strip():
        uid = x_user_id.strip()
        if not _USER_ID_RE.match(uid):
            raise HTTPException(status_code=400, detail="Invalid user id.")
        return {
            "user_id": uid, "provider": "dev", "sub": uid,
            "email": None, "email_verified": False, "name": None,
        }

    raise HTTPException(status_code=401, detail="Not authenticated.")


def get_user_id(
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None, alias="x-user-id"),
) -> str:
    """Convenience dependency — just the canonical user_id."""
    return get_current_user(authorization, x_user_id)["user_id"]


def require_admin(
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None, alias="x-user-id"),
) -> str:
    """
    Gate for /admin/*. In dev-bypass mode the local dashboard works without
    headers; otherwise the verified user must be in the ADMIN_USER_IDS
    allowlist (comma-separated provider-scoped ids, e.g. "google:1234,apple:001.ab").
    """
    if _dev_bypass_enabled():
        return x_user_id.strip() if x_user_id and x_user_id.strip() else "dev-admin"

    user = get_current_user(authorization, x_user_id)
    allowlist = {
        x.strip() for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
    }
    if user["user_id"] not in allowlist:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user["user_id"]
