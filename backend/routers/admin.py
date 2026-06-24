"""
Admin endpoints — local use only.
GET /admin/            — serve dashboard HTML
GET /admin/stats       — aggregate counts
GET /admin/users       — all users with transcript metadata
GET /admin/majors      — all programs with signup + course counts
GET /admin/courses     — paginated/searchable course rows
"""

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pathlib import Path

from db import requirements_table, users_table, transcript_table

router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/", include_in_schema=False)
def admin_dashboard():
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

@router.get("/stats")
def get_stats():
    """High-level counts for the dashboard header."""
    users = _scan_all(users_table, ProjectionExpression="user_id, major, transcript_parsed_at")
    reqs  = _scan_all(requirements_table, ProjectionExpression="program_name")

    majors      = {r["program_name"] for r in reqs}
    with_transcript = sum(1 for u in users if u.get("transcript_parsed_at"))

    return {
        "total_users":           len(users),
        "users_with_transcript": with_transcript,
        "total_majors":          len(majors),
        "total_requirement_rows": len(reqs),
    }


@router.get("/users")
def get_users():
    """Return all user records with transcript metadata."""
    users = _scan_all(users_table)
    result = []
    for u in users:
        result.append({
            "user_id":              u.get("user_id"),
            "major":                u.get("major", "—"),
            "subplan":              u.get("subplan", ""),
            "transcript_parsed_at": u.get("transcript_parsed_at", ""),
            "transcript_s3_key":    u.get("transcript_s3_key", ""),
        })
    result.sort(key=lambda x: x["transcript_parsed_at"] or "", reverse=True)
    return {"users": result, "count": len(result)}


@router.get("/majors")
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


@router.get("/courses")
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
