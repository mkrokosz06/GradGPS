"""
Passwordless email sign-in codes (one-time 6-digit codes).

A code is emailed to a user; verifying it proves control of the inbox and
mints a session (see routers/email_auth.py). Codes are stored in the existing
`sessions` table — reusing its DynamoDB TTL and IAM grant so no new prod table
or role change is needed — under a distinct key namespace, and only a SHA-256
of the code is persisted (a table dump can't reveal live codes).
"""

import hashlib
import secrets
import time

from db import sessions_table

CODE_TTL_SECONDS = 600   # 10 minutes
MAX_ATTEMPTS     = 5     # wrong guesses before the code is burned


def _key(email: str) -> dict:
    # Namespaced so a code row can never collide with a real session row
    # (whose key is sha256 of an unguessable sess_ token).
    return {"token_hash": hashlib.sha256(f"emailcode:{email}".encode()).hexdigest()}


def _code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()


def issue_code(email: str) -> str:
    """Generate, store, and return a fresh 6-digit code for `email`.

    Overwrites any outstanding code for the same email (only the latest is
    valid). Returns the plaintext code for the caller to email.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = int(time.time())
    sessions_table.put_item(Item={
        **_key(email),
        "kind":       "email_code",
        "code_hash":  _code_hash(email, code),
        "attempts":   0,
        "created_at": now,
        "expires_at": now + CODE_TTL_SECONDS,  # doubles as the DynamoDB TTL
    })
    return code


def check_code(email: str, code: str) -> bool:
    """True iff `code` is the current, unexpired code for `email`.

    Consumes the code on success. Wrong guesses increment an attempt counter
    and burn the code once MAX_ATTEMPTS is reached, so a code can't be
    brute-forced within its 10-minute lifetime.
    """
    key = _key(email)
    item = sessions_table.get_item(Key=key).get("Item")
    if not item or item.get("kind") != "email_code":
        return False

    now = int(time.time())
    if now >= int(item["expires_at"]):
        sessions_table.delete_item(Key=key)
        return False

    if int(item.get("attempts", 0)) >= MAX_ATTEMPTS:
        sessions_table.delete_item(Key=key)
        return False

    if item["code_hash"] != _code_hash(email, code):
        sessions_table.update_item(
            Key=key,
            UpdateExpression="SET attempts = attempts + :one",
            ExpressionAttributeValues={":one": 1},
        )
        return False

    sessions_table.delete_item(Key=key)  # single-use
    return True
