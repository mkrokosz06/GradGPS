"""
Charlie router — the "add my school" agent's HTTP surface.

Public (no auth — same posture as the support form):
    POST /charlie/request           capture + normalize a school request, +1 vote

Admin (require_admin — local dashboard / allowlisted ids):
    GET  /charlie/schools           demand ranking (votes desc)
    GET  /charlie/schools/{key}     one request record (incl. last readiness report)
    POST /charlie/schools/{key}/triage   run feasibility triage, store the report
    GET  /charlie/dashboard         founder dashboard HTML

Abuse control on the public endpoint mirrors support.py: honeypot field +
per-sender in-memory sliding-window rate limit. Demand is stored one row per
canonical school in the `school_requests` table; votes accumulate atomically so
"PSU" and "Pennsylvania State University" land on the same row.
"""

import re
import time
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Header, Request, Depends, Query
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel

import charlie
from db import school_requests_table
from deps import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent / "static"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Sliding-window rate limit — N requests / window / sender.
_RATE_LIMIT = 8
_RATE_WINDOW = 3600
_recent: dict[str, deque] = defaultdict(deque)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_ip(request: Request) -> str:
    # Rightmost X-Forwarded-For hop is the trusted one behind App Runner.
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[-1].strip() or (request.client.host if request.client else "unknown")


def _rate_limited(key: str) -> bool:
    now = time.time()
    q = _recent[key]
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return True
    q.append(now)
    return False


# ── Public: capture a request ─────────────────────────────────────────────────

class SchoolRequestBody(BaseModel):
    school:  str
    email:   str | None = None   # optional "notify me when it's added"
    website: str | None = None   # honeypot — real users never fill this


@router.post("/request")
def request_school(body: SchoolRequestBody, request: Request):
    # Honeypot filled → bot. Report success so it doesn't adapt.
    if body.website and body.website.strip():
        return {"ok": True}

    resolved = charlie.normalize_school(body.school)
    if not resolved:
        raise HTTPException(status_code=400, detail="Please enter your school's name.")

    if _rate_limited(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many requests — please try again later.")

    email = (body.email or "").strip().lower()
    if email and (not _EMAIL_RE.match(email) or len(email) > 254):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    alias_seen = body.school.strip()[:100]
    now = _now()

    set_clauses = [
        "canonical_name = :name",
        "matched = :m",
        "last_requested_at = :now",
        "first_requested_at = if_not_exists(first_requested_at, :now)",
        "#st = if_not_exists(#st, :req)",
    ]
    add_clauses = ["votes :one", "aliases_seen :al"]
    names = {"#st": "status"}
    values = {
        ":name": resolved["canonical_name"],
        ":m":    resolved["matched"],
        ":now":  now,
        ":req":  "requested",
        ":one":  1,
        ":al":   {alias_seen},
    }
    if email:
        add_clauses.append("notify_emails :em")
        values[":em"] = {email}

    try:
        school_requests_table.update_item(
            Key={"school_key": resolved["school_key"]},
            UpdateExpression="SET " + ", ".join(set_clauses) + " ADD " + ", ".join(add_clauses),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except Exception:
        logger.exception("Failed to record school request for %r", resolved["school_key"])
        raise HTTPException(status_code=502, detail="Couldn't save your request — please try again.")

    # Deliberately do NOT echo the resolved canonical name/match back to an
    # anonymous caller — nothing useful for them, and it leaks the roster.
    return {"ok": True}


# ── Admin: demand + triage ────────────────────────────────────────────────────

def _scan_all(table, **kwargs) -> list[dict]:
    items: list[dict] = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def _serialize(item: dict) -> dict:
    """DynamoDB numbers come back as Decimal and sets as Python set — make JSON-safe."""
    return {
        "school_key":         item.get("school_key"),
        "canonical_name":     item.get("canonical_name"),
        "matched":            bool(item.get("matched", False)),
        "votes":              int(item.get("votes") or 0),
        "status":             item.get("status", "requested"),
        "aliases_seen":       sorted(item.get("aliases_seen", []) or []),
        "notify_count":       len(item.get("notify_emails", []) or []),
        "first_requested_at": item.get("first_requested_at"),
        "last_requested_at":  item.get("last_requested_at"),
        "triaged_at":         item.get("triaged_at"),
        "readiness":          item.get("readiness"),
    }


@router.get("/schools", dependencies=[Depends(require_admin)])
def list_schools():
    items = [_serialize(i) for i in _scan_all(school_requests_table)]
    items.sort(key=lambda x: x["votes"], reverse=True)
    return {
        "schools": items,
        "count":   len(items),
        "total_votes": sum(s["votes"] for s in items),
        "matched":     sum(1 for s in items if s["matched"]),
        "triaged":     sum(1 for s in items if s["triaged_at"]),
    }


@router.get("/schools/{school_key}", dependencies=[Depends(require_admin)])
def get_school(school_key: str):
    item = school_requests_table.get_item(Key={"school_key": school_key}).get("Item")
    if not item:
        raise HTTPException(status_code=404, detail="No such school request.")
    return _serialize(item)


@router.post("/schools/{school_key}/triage", dependencies=[Depends(require_admin)])
async def triage_school(
    school_key: str,
    catalog_url: str | None = Query(None, description="Optional catalog URL for Charlie to probe"),
):
    item = school_requests_table.get_item(Key={"school_key": school_key}).get("Item")
    if not item:
        raise HTTPException(status_code=404, detail="No such school request.")

    report = await charlie.run_triage({**item, "school_key": school_key}, catalog_url=catalog_url)
    now = _now()
    school_requests_table.update_item(
        Key={"school_key": school_key},
        UpdateExpression="SET readiness = :r, triaged_at = :t, #st = :s",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":r": report, ":t": now, ":s": "triaged"},
    )
    return {"school_key": school_key, "triaged_at": now, "readiness": report}


@router.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "charlie.html")
