"""
POST /support/contact — support form from the mobile app and gradgps.com.

The sender's address never reaches the client: SUPPORT_EMAIL (the destination)
lives only in the server environment. Messages are delivered via SES with the
student's address as Reply-To, so replying in Gmail goes straight back to them.

Env:
    SUPPORT_EMAIL       destination inbox (unset = dev mode: log only, no SES)
    SUPPORT_FROM_EMAIL  verified SES sender (defaults to SUPPORT_EMAIL)

No auth required — the website form is anonymous — but a valid bearer token /
dev x-user-id is attached to the message when present. Abuse control is a
per-sender in-memory rate limit plus a honeypot field the website form hides.
"""

import os
import re
import time
import logging
from collections import defaultdict, deque

import boto3
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel

from deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MAX_MESSAGE = 5000
_MIN_MESSAGE = 10
_MAX_SUBJECT = 200

# Sliding-window rate limit: N messages per window per sender (user_id when
# authenticated, else client IP). In-memory is fine — App Runner runs at most
# two instances, and the worst case of a restart is a reset window.
_RATE_LIMIT = 5
_RATE_WINDOW = 3600  # seconds
_recent: dict[str, deque] = defaultdict(deque)


class ContactBody(BaseModel):
    email:   str
    message: str
    subject: str | None = None
    website: str | None = None  # honeypot — humans never see or fill this


def _client_key(request: Request, user_id: str | None) -> str:
    if user_id:
        return f"user:{user_id}"
    # App Runner terminates TLS and forwards the caller IP in X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


def _rate_limited(key: str) -> bool:
    now = time.time()
    q = _recent[key]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return True
    q.append(now)
    return False


def _optional_user_id(authorization: str | None, x_user_id: str | None) -> str | None:
    if not authorization and not x_user_id:
        return None
    try:
        return get_current_user(authorization, x_user_id)["user_id"]
    except HTTPException:
        return None


def _send_via_ses(dest: str, reply_to: str, subject: str, body: str) -> None:
    sender = os.getenv("SUPPORT_FROM_EMAIL", "").strip() or dest
    ses = boto3.client("sesv2", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    ses.send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [dest]},
        ReplyToAddresses=[reply_to],
        Content={"Simple": {
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        }},
    )


@router.post("/contact")
def contact(
    body: ContactBody,
    request: Request,
    authorization: str | None = Header(None),
    x_user_id: str | None = Header(None, alias="x-user-id"),
):
    # Honeypot filled → bot. Report success so it doesn't adapt.
    if body.website and body.website.strip():
        return {"ok": True}

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    message = body.message.strip()
    if len(message) < _MIN_MESSAGE:
        raise HTTPException(status_code=400, detail="Please describe your issue in a bit more detail.")
    if len(message) > _MAX_MESSAGE:
        raise HTTPException(status_code=400, detail=f"Message is too long (max {_MAX_MESSAGE} characters).")

    subject = (body.subject or "").strip()[:_MAX_SUBJECT] or "Support request"

    user_id = _optional_user_id(authorization, x_user_id)
    if _rate_limited(_client_key(request, user_id)):
        raise HTTPException(
            status_code=429,
            detail="Too many messages — please wait a bit before sending another.",
        )

    mail_body = (
        f"{message}\n\n"
        f"---\n"
        f"From:    {email}\n"
        f"User:    {user_id or 'not signed in'}\n"
        f"Origin:  {request.headers.get('origin') or 'mobile app'}\n"
    )

    dest = os.getenv("SUPPORT_EMAIL", "").strip()
    if not dest:
        # Dev mode — no SES configured; just log the message.
        logger.info("Support message (dev, not sent): %s | %s | %s", email, subject, message)
        return {"ok": True}

    try:
        _send_via_ses(dest, email, f"[GradGPS Support] {subject}", mail_body)
    except Exception:
        logger.exception("SES send failed for support message from %s", email)
        raise HTTPException(
            status_code=502,
            detail="We couldn't send your message right now. Please try again later.",
        )
    return {"ok": True}
