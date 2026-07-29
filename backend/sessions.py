"""
Server-issued opaque session tokens.

Google/Apple ID tokens expire after ~1 hour, which used to log users out
hourly. POST /auth/session exchanges a freshly verified ID token for a
long-lived opaque token (`sess_<random>`), which the client then sends as
Bearer on every request; deps.get_current_user resolves it here.

Storage: `sessions` table, PK = SHA-256 of the token (the raw token is never
persisted — a table dump can't be replayed). `expires_at` is a DynamoDB TTL
attribute for automatic cleanup, but validity is also enforced at read time
because TTL deletion can lag by up to ~48 h.

Expiry is sliding: any authenticated request within the 30-day window pushes
it out another 30 days (bumped at most ~daily to avoid a write per request).
"""

import hashlib
import secrets
import time

from db import sessions_table

SESSION_PREFIX      = "sess_"
SESSION_TTL_SECONDS = 30 * 24 * 3600
_BUMP_AFTER_SECONDS = 24 * 3600   # refresh expiry at most once a day


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(claims: dict) -> dict:
    """
    Mint a session for verified identity claims (verify_id_token output).
    Returns {"token", "expires_at"}.
    """
    token = SESSION_PREFIX + secrets.token_urlsafe(32)
    now = int(time.time())
    item = {
        "token_hash":     _token_hash(token),
        "user_id":        claims["user_id"],
        "provider":       claims.get("provider"),
        "sub":            claims.get("sub"),
        "email":          claims.get("email"),
        "email_verified": bool(claims.get("email_verified")),
        "name":           claims.get("name"),
        "created_at":     now,
        "expires_at":     now + SESSION_TTL_SECONDS,
    }
    sessions_table.put_item(Item={k: v for k, v in item.items() if v is not None})
    return {"token": token, "expires_at": item["expires_at"]}


def resolve_session(token: str) -> dict | None:
    """
    Identity claims for a valid session token (same shape as
    verify_id_token), or None if unknown/expired.
    """
    key = {"token_hash": _token_hash(token)}
    item = sessions_table.get_item(Key=key).get("Item")
    if not item:
        return None

    now = int(time.time())
    expires_at = int(item["expires_at"])
    if now >= expires_at:
        return None

    if expires_at - now < SESSION_TTL_SECONDS - _BUMP_AFTER_SECONDS:
        sessions_table.update_item(
            Key=key,
            UpdateExpression="SET expires_at = :e",
            ExpressionAttributeValues={":e": now + SESSION_TTL_SECONDS},
        )

    return {
        "user_id":        item["user_id"],
        "provider":       item.get("provider"),
        "sub":            item.get("sub"),
        "email":          item.get("email"),
        "email_verified": bool(item.get("email_verified")),
        "name":           item.get("name"),
    }


def revoke_session(token: str) -> None:
    """Delete a session. Idempotent — unknown tokens are a no-op."""
    sessions_table.delete_item(Key={"token_hash": _token_hash(token)})
