"""
Admin endpoints — local use only.
GET /admin/            — serve dashboard HTML
GET /admin/stats       — aggregate counts
GET /admin/users       — all users with transcript metadata
GET /admin/majors      — all programs with signup + course counts
GET /admin/courses     — paginated/searchable course rows
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Query, Depends
from fastapi.responses import FileResponse
from pathlib import Path

from db import requirements_table, users_table, transcript_table
from deps import require_admin

router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent / "static"

# Data endpoints are gated per-route (below) so the dashboard *shell* can load
# without auth and present a Google sign-in. Every endpoint that returns data
# carries Depends(require_admin); only the static shell is public.
_admin = [Depends(require_admin)]


@router.get("/", include_in_schema=False)
def admin_dashboard():
    # Public shell — contains no data; it must sign in to call the endpoints below.
    return FileResponse(STATIC_DIR / "admin.html")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_all(table, **kwargs) -> list[dict]:
    """Paginate through an entire DynamoDB table scan."""
    items: list[dict] = []
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", dependencies=_admin)
def get_stats():
    """
    Signup + activation funnel. Scans only the (small) users table — no
    requirements scan — so it's cheap to poll/auto-refresh.

    Activation is split: a user counts toward `added_major` once they pick a
    major and `added_transcript` once a transcript is parsed. `activated` is
    either signal; `fully_set_up` is both. Time buckets rely on `created_at`
    (added on account creation going forward) — users created before that
    field existed are counted in totals but not in new_today/new_this_week.
    """
    users = _scan_all(
        users_table,
        ProjectionExpression="user_id, major, transcript_parsed_at, created_at",
    )

    now         = datetime.now(timezone.utc)
    today       = now.date().isoformat()          # e.g. "2026-08-18"
    week_cutoff = (now - timedelta(days=7)).isoformat()

    added_major      = 0
    added_transcript = 0
    fully_set_up     = 0
    activated        = 0
    new_today        = 0
    new_this_week    = 0
    dated_users      = 0

    for u in users:
        has_major      = bool(u.get("major"))
        has_transcript = bool(u.get("transcript_parsed_at"))
        if has_major:
            added_major += 1
        if has_transcript:
            added_transcript += 1
        if has_major and has_transcript:
            fully_set_up += 1
        if has_major or has_transcript:
            activated += 1

        created = u.get("created_at")
        if created:
            dated_users += 1
            if created[:10] == today:
                new_today += 1
            if created >= week_cutoff:
                new_this_week += 1

    return {
        "total_users":      len(users),
        "added_major":      added_major,
        "added_transcript": added_transcript,
        "activated":        activated,       # major OR transcript
        "fully_set_up":     fully_set_up,    # major AND transcript
        "new_today":        new_today,
        "new_this_week":    new_this_week,
        # how many rows carry a created_at yet (transparency for the time buckets)
        "dated_users":      dated_users,
    }


@router.get("/users", dependencies=_admin)
def get_users():
    """Return all user records with transcript metadata."""
    users = _scan_all(users_table)
    result = []
    for u in users:
        result.append({
            "user_id":              u.get("user_id"),
            "name":                 u.get("name", ""),
            "major":                u.get("major", "—"),
            "subplan":              u.get("subplan", ""),
            "transcript_parsed_at": u.get("transcript_parsed_at", ""),
            "transcript_s3_key":    u.get("transcript_s3_key", ""),
        })
    result.sort(key=lambda x: x["transcript_parsed_at"] or "", reverse=True)
    return {"users": result, "count": len(result)}


@router.get("/majors", dependencies=_admin)
def get_majors():
    """Return all programs with per-program course count and signup count."""
    # Requirements scan — just program_name and course_code to count rows
    req_items = _scan_all(
        requirements_table,
        ProjectionExpression="program_name, course_code, college, degree",
    )
    # Users scan — just major field
    user_items = _scan_all(users_table, ProjectionExpression="major")

    # Build signup counts
    signup_counts: dict[str, int] = {}
    for u in user_items:
        m = u.get("major", "")
        if m:
            signup_counts[m] = signup_counts.get(m, 0) + 1

    # Build per-program stats
    program_map: dict[str, dict] = {}
    for r in req_items:
        name = r["program_name"]
        if name not in program_map:
            program_map[name] = {
                "program_name": name,
                "college":      r.get("college", ""),
                "degree":       r.get("degree", ""),
                "course_count": 0,
                "signups":      signup_counts.get(name, 0),
            }
        program_map[name]["course_count"] += 1

    majors = sorted(program_map.values(), key=lambda x: x["program_name"])
    return {"majors": majors, "count": len(majors)}


@router.get("/courses", dependencies=_admin)
def get_courses(
    major:  str  = Query(None,  description="Filter by exact program name"),
    search: str  = Query(None,  description="Substring search on course_code or title"),
    limit:  int  = Query(200,   ge=1, le=1000),
    offset: int  = Query(0,     ge=0),
):
    """Return requirement rows, optionally filtered by major and/or search term."""
    scan_kwargs: dict = {
        "ProjectionExpression":
            "program_name, requirement_group, course_code, course_title, credits, min_grade, group_type",
    }

    if major:
        from boto3.dynamodb.conditions import Key
        # Use query instead of scan when major is specified
        items = []
        resp_kwargs = {
            "KeyConditionExpression": Key("program_name").eq(major),
            "ProjectionExpression": scan_kwargs["ProjectionExpression"],
        }
        while True:
            resp = requirements_table.query(**resp_kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            resp_kwargs["ExclusiveStartKey"] = last
    else:
        items = _scan_all(requirements_table, **scan_kwargs)

    # Apply search filter
    if search:
        s = search.lower()
        items = [
            i for i in items
            if s in i.get("course_code", "").lower()
            or s in i.get("course_title", "").lower()
        ]

    total = len(items)
    page  = items[offset: offset + limit]

    return {"courses": page, "total": total, "offset": offset, "limit": limit}
