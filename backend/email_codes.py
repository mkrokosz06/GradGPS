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

from botocore.exceptions import ClientError

from db import sessions_table

CODE_TTL_SECONDS = 600   # 10 minutes
MAX_ATTEMPTS     = 5     # wrong guesses before the code is burned
# A second /start within this window (double-tapped button, button + keyboard
# "done", a client retry) must NOT mint a fresh code and orphan the one already
# emailed — otherwise the user receives a code that was overwritten in the DB
# and gets "invalid or expired" for typing exactly what they were sent. Inside
# the window `issue_code` keeps the live code; outside it (or once expired) a
# genuine "resend" still gets a new one.
REISSUE_MIN_INTERVAL = 15  # seconds


def _key(email: str) -> dict:
    # Namespaced so a code row can never collide with a real session row
    # (whose key is sha256 of an unguessable sess_ token).
    return {"token_hash": hashlib.sha256(f"emailcode:{email}".encode()).hexdigest()}


def _code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}:{code}".encode()).hexdigest()


def issue_code(email: str) -> str | None:
    """Generate and store a fresh 6-digit code for `email`.

    Returns the plaintext code for the caller to email, or ``None`` when a code
    was issued less than ``REISSUE_MIN_INTERVAL`` seconds ago — in that case the
    live code is left untouched and the caller must NOT send another email (the
    already-delivered code is still the valid one). A conditional write makes
    this safe against truly concurrent /start calls: only one wins, and only its
    plaintext is ever returned/emailed.

    A code older than the window (or already expired) is replaced, so a genuine
    "resend" still gets a new code.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = int(time.time())
    try:
        sessions_table.put_item(
            Item={
                **_key(email),
                "kind":       "email_code",
                "code_hash":  _code_hash(email, code),
                "attempts":   0,
                "created_at": now,
                "expires_at": now + CODE_TTL_SECONDS,  # doubles as the DynamoDB TTL
            },
            # Overwrite only when there's no code yet or the existing one is
            # older than the reissue window; a recent code makes this a no-op.
            ConditionExpression="attribute_not_exists(token_hash) OR #ca <= :cutoff",
            ExpressionAttributeNames={"#ca": "created_at"},
            ExpressionAttributeValues={":cutoff": now - REISSUE_MIN_INTERVAL},
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return None
        raise
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
