"""
POST   /auth/session — exchange a verified Google/Apple ID token for a
                       long-lived opaque session token (fixes the ~1 h
                       ID-token expiry logging users out).
DELETE /auth/session — revoke the caller's session (sign-out).
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from auth import verify_id_token, TokenVerificationError
from sessions import SESSION_PREFIX, create_session, revoke_session

router = APIRouter()


class SessionBody(BaseModel):
    id_token: str


@router.post("/session")
def create_session_route(body: SessionBody):
    """
    The ID token is fully verified (signature, issuer, audience, expiry)
    before a session is minted — this endpoint needs no other auth.
    """
    try:
        claims = verify_id_token(body.id_token.strip())
    except TokenVerificationError as e:
        raise HTTPException(status_code=401, detail=str(e))

    session = create_session(claims)
    return {
        "session_token": session["token"],
        "expires_at":    session["expires_at"],
        "user_id":       claims["user_id"],
        "name":          claims.get("name"),
        "email":         claims.get("email"),
    }


@router.delete("/session")
def revoke_session_route(authorization: str | None = Header(None)):
    """Idempotent sign-out: revoking an unknown/expired token still succeeds."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(SESSION_PREFIX):
        raise HTTPException(status_code=400, detail="Expected: Bearer <session token>.")
    revoke_session(token)
    return {"revoked": True}
