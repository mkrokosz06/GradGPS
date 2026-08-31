"""
Passwordless email sign-in (one-time code).

POST /auth/email/start  { email }              -> emails a 6-digit code
POST /auth/email/verify { email, code, name? } -> mints a session

This is a self-contained alternative to Google/Apple: proving control of an
inbox is the authentication. The canonical id is `email:<normalized-email>`,
so an email user is distinct from the same person's google:/apple: identity.

Codes go out via SES using the same verified sender as the support form
(SUPPORT_FROM_EMAIL). With SUPPORT_FROM_EMAIL unset (local dev), or under
AUTH_DEV_BYPASS, the code is logged instead of emailed so dev can test without
SES. NOTE: until SES production access is granted, SES only delivers to
*verified* recipients — real user inboxes will bounce in the sandbox.
"""

import os
import re
import secrets
import time
import logging
from collections import defaultdict, deque

import boto3
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from email_codes import issue_code, check_code
from sessions import create_session

logger = logging.getLogger(__name__)
router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_NAME = 100

# Sliding-window rate limits (in-memory; App Runner runs <=2 instances, and a
# restart just resets the window). Keyed by email for /start and by IP as a
# backstop so one host can't farm codes for many addresses.
_START_PER_EMAIL   = 5      # codes per window per email
_START_PER_IP      = 20     # codes per window per IP
_RATE_WINDOW       = 3600   # seconds
_by_email: dict[str, deque] = defaultdict(deque)
_by_ip:    dict[str, deque] = defaultdict(deque)


class StartBody(BaseModel):
    email: str


class VerifyBody(BaseModel):
    email: str
    code:  str
    name:  str | None = None


def _client_ip(request: Request) -> str:
    # App Runner appends the real caller IP to the RIGHT of X-Forwarded-For;
    # the rightmost hop is the trusted one (leftmost is client-controllable).
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[-1].strip() or (request.client.host if request.client else "unknown")


def _rate_limited(bucket: dict[str, deque], key: str, limit: int) -> bool:
    now = time.time()
    q = bucket[key]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def _dev_mode() -> bool:
    return os.getenv("AUTH_DEV_BYPASS", "").strip().lower() in {"1", "true", "yes"}


def _review_account() -> tuple[str, str] | None:
    """App Store review demo account (REVIEW_EMAIL + REVIEW_CODE env vars).

    Apple's reviewer can't read a real inbox, so this one address signs in
    with a fixed 6-digit code and no email is ever sent. Returns (email, code)
    when configured, else None (feature fully disabled)."""
    email = os.getenv("REVIEW_EMAIL", "").strip().lower()
    code = os.getenv("REVIEW_CODE", "").strip()
    if email and len(code) == 6 and code.isdigit():
        return email, code
    return None


def _send_code_email(sender: str, dest: str, code: str) -> None:
    ses = boto3.client("sesv2", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    body = (
        f"Your GradGPS sign-in code is:\n\n"
        f"    {code}\n\n"
        f"It expires in 10 minutes. If you didn't request it, you can ignore this email.\n"
    )
    ses.send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [dest]},
        Content={"Simple": {
            "Subject": {"Data": "Your GradGPS sign-in code"},
            "Body": {"Text": {"Data": body}},
        }},
    )


@router.post("/email/start")
def email_start(body: StartBody, request: Request):
    """Email a one-time code. Always returns a generic success (no account
    enumeration) once basic validation and rate limits pass."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    review = _review_account()
    if review and email == review[0]:
        # Fixed-code demo account: nothing to issue or send, and no rate
        # limiting so reviewer retries can never 429.
        return {"ok": True}

    if _rate_limited(_by_ip, _client_ip(request), _START_PER_IP) or \
       _rate_limited(_by_email, email, _START_PER_EMAIL):
        raise HTTPException(
            status_code=429,
            detail="Too many code requests — please wait a bit before trying again.",
        )

    code = issue_code(email)
    if code is None:
        # A code was just issued (double-submit / retry); the one already sent
        # is still valid. Don't mint or email a second one that would orphan it.
        return {"ok": True}

    sender = os.getenv("SUPPORT_FROM_EMAIL", "").strip()
    if not sender or _dev_mode():
        # Dev / unconfigured: don't send, just log so testing works without SES.
        logger.info("Email sign-in code for %s (not sent): %s", email, code)
        return {"ok": True}

    try:
        _send_code_email(sender, email, code)
    except Exception:
        logger.exception("SES send failed for email sign-in code to %s", email)
        raise HTTPException(
            status_code=502,
            detail="We couldn't send your code right now. Please try again later.",
        )
    return {"ok": True}


@router.post("/email/verify")
def email_verify(body: VerifyBody):
    """Verify the code and mint a session (same response shape as
    POST /auth/session)."""
    email = body.email.strip().lower()
    code  = body.code.strip()
    if not _EMAIL_RE.match(email) or not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="Enter the 6-digit code we emailed you.")

    review = _review_account()
    if review and email == review[0]:
        ok = secrets.compare_digest(code, review[1])
    else:
        ok = check_code(email, code)
    if not ok:
        raise HTTPException(status_code=401, detail="That code is invalid or has expired.")

    name = (body.name or "").strip()[:_MAX_NAME] or None
    claims = {
        "user_id":        f"email:{email}",
        "provider":       "email",
        "sub":            email,
        "email":          email,
        "email_verified": True,   # proven by receiving the code
        "name":           name,
    }
    session = create_session(claims)
    return {
        "session_token": session["token"],
        "expires_at":    session["expires_at"],
        "user_id":       claims["user_id"],
        "name":          name,
        "email":         email,
    }
