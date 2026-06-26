"""
RateMyProfessors GraphQL client + course-index helpers.

Public surface:
  normalize_course_code(raw)          — clean up student-typed RMP class strings
  search_professor(name, school_id)   — name search at a school
  get_course_ratings(teacher_id, code)— course-specific rating aggregates
  get_professors_for_course(code)     — index lookup: who teaches this course?
"""

import re
import asyncio
import httpx
from decimal import Decimal

RMP_GRAPHQL   = "https://www.ratemyprofessors.com/graphql"
PSU_SCHOOL_ID = "U2Nob29sLTc1OA=="   # School-758 = Penn State University (State College, PA)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Authorization": "Basic dGVzdDp0ZXN0",   # required by RMP's GraphQL endpoint
    "Referer": "https://www.ratemyprofessors.com/",
    "Origin":  "https://www.ratemyprofessors.com",
}

# ── Course code normalization ─────────────────────────────────────────────────

_ALIASES: dict[str, str] = {
    "MAT":   "MATH",  "CALC":  "MATH",  "STA":   "STAT",  "STATS": "STAT",
    "PSYC":  "PSYCH", "BIO":   "BIOL",  "COMP":  "CMPSC", "CS":    "CMPSC",
    "ACCT":  "ACCTG", "ACC":   "ACCTG",
    "EARTH": "GEOSC", "GEO":   "GEOSC",
    "COMM":  "COMM",  "KINES": "KINES", "NURS":  "NURS",
}


def normalize_course_code(raw: str) -> str | None:
    """
    Convert a student-typed RMP class string to canonical PSU format "SUBJECT NUMBER".
    Returns None if the string doesn't look like a course code.

    Examples:
      "mat140"    -> "MATH 140"
      "IST301"    -> "IST 301"
      "ist 301w"  -> "IST 301"      (W suffix stripped)
      "CMPSC 121" -> "CMPSC 121"
      "calc 2"    -> "MATH 2"
      "professor" -> None
    """
    if not raw or len(raw) > 20:
        return None
    s = raw.strip().upper()
    s = re.sub(r"[^A-Z0-9\s]", "", s)   # strip punctuation
    s = re.sub(r"\s+", "", s)            # collapse spaces
    # Strip PSU attribute suffixes (W=Writing, H=Honors, N=Non-Western)
    s = re.sub(r"([A-Z]{2,6}\d{1,4})[WHN]$", r"\1", s)
    # Must be: 2-6 alpha + 1-4 digits + optional single letter section
    m = re.match(r"^([A-Z]{2,6})(\d{1,4}[A-Z]?)$", s)
    if not m:
        return None
    subject, number = m.group(1), m.group(2)
    subject = _ALIASES.get(subject, subject)
    return f"{subject} {number}"


def _normalize_for_match(code: str) -> str:
    """Internal: collapse 'IST 301W' -> 'IST301' for matching ratings."""
    code = code.strip().upper()
    code = re.sub(r"[WHN]$", "", code)
    return re.sub(r"\s+", "", code)


# ── Index lookup ──────────────────────────────────────────────────────────────

async def get_professors_for_course(
    course_code: str,
    limit: int = 5,
) -> list[dict]:
    """
    Query the rmp_professor_courses DynamoDB index for professors who have been
    rated in this course. Returns up to `limit` entries sorted by overall rating
    descending.

    Each entry: { professor_id, name, department, overall_avg_rating,
                  overall_avg_difficulty, overall_num_ratings }

    Returns [] if the table is empty or the course has no index entries.
    """
    # Import here to avoid circular imports when this module is used standalone
    from db import get_dynamodb
    from boto3.dynamodb.conditions import Key

    norm = normalize_course_code(course_code)
    if not norm:
        norm = course_code.strip().upper()

    try:
        db    = get_dynamodb()
        table = db.Table("rmp_professor_courses")
        resp  = table.query(
            KeyConditionExpression=Key("course_code").eq(norm),
        )
        items = resp.get("Items", [])
        # Sort by overall_avg_rating desc, take top N
        items.sort(key=lambda x: float(x.get("overall_avg_rating") or 0), reverse=True)
        return [
            {
                "professor_id":       item["professor_id"],
                "name":               item.get("name", ""),
                "department":         item.get("department"),
                "overall_avg_rating": float(item["overall_avg_rating"]) if item.get("overall_avg_rating") else None,
                "overall_avg_difficulty": float(item["overall_avg_difficulty"]) if item.get("overall_avg_difficulty") else None,
                "overall_num_ratings": int(item.get("overall_num_ratings") or 0),
            }
            for item in items[:limit]
        ]
    except Exception:
        return []


# ── Name search ───────────────────────────────────────────────────────────────

async def search_professor(name: str, school_id: str = PSU_SCHOOL_ID) -> list[dict]:
    """
    Return up to 5 RMP teacher matches for `name` at the given school.
    Each result: id, firstName, lastName, avgRating, avgDifficulty,
                 wouldTakeAgainPercent, numRatings, department.
    """
    body = {
        "query": """
        query TeacherSearchResultsPageQuery($query: TeacherSearchQuery!) {
          search: newSearch {
            teachers(query: $query, first: 5) {
              edges {
                node {
                  id
                  firstName
                  lastName
                  avgRating
                  avgDifficulty
                  wouldTakeAgainPercent
                  numRatings
                  department
                }
              }
            }
          }
        }
        """,
        "variables": {"query": {"text": name, "schoolID": school_id}},
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(RMP_GRAPHQL, json=body, headers=_HEADERS)
        resp.raise_for_status()

    edges = (
        resp.json()
        .get("data", {})
        .get("search", {})
        .get("teachers", {})
        .get("edges", [])
    )
    return [e["node"] for e in edges if e.get("node")]


# ── Course-specific ratings ───────────────────────────────────────────────────

async def get_course_ratings(teacher_id: str, course_code: str) -> dict:
    """
    Fetch ratings for a teacher filtered to a specific course code.

    Uses RMP's courseFilter for server-side pre-filtering, then applies
    our own normalized comparison to catch "IST301" / "ist 301" variants.

    Returns course-specific aggregates (course_avg_rating, etc.) plus
    overall teacher aggregates for context.

    wouldTakeAgain in individual ratings: 1=yes, 0=no, -1=N/A (excluded).
    """
    norm_target = _normalize_for_match(course_code)

    body = {
        "query": """
        query RatingsForTeacher($id: ID!, $courseFilter: String) {
          node(id: $id) {
            ... on Teacher {
              numRatings
              avgRating
              avgDifficulty
              wouldTakeAgainPercent
              ratings(courseFilter: $courseFilter) {
                edges {
                  node {
                    class
                    qualityRating
                    difficultyRatingRounded
                    wouldTakeAgain
                  }
                }
              }
            }
          }
        }
        """,
        "variables": {"id": teacher_id, "courseFilter": norm_target},
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(RMP_GRAPHQL, json=body, headers=_HEADERS)
        resp.raise_for_status()

    node  = resp.json().get("data", {}).get("node") or {}
    edges = node.get("ratings", {}).get("edges", [])

    course_ratings = [
        e["node"] for e in edges
        if _normalize_for_match(e.get("node", {}).get("class") or "") == norm_target
    ]

    def _avg(vals: list) -> float | None:
        cleaned = [v for v in vals if v is not None]
        return round(sum(cleaned) / len(cleaned), 1) if cleaned else None

    quality  = [r.get("qualityRating")          for r in course_ratings]
    diff     = [r.get("difficultyRatingRounded") for r in course_ratings]
    wta_vals = [r["wouldTakeAgain"] for r in course_ratings
                if r.get("wouldTakeAgain", -1) not in (-1, None)]
    wta_pct  = round(sum(wta_vals) / len(wta_vals) * 100) if wta_vals else None

    overall_wta = node.get("wouldTakeAgainPercent")
    return {
        "course_avg_rating":       _avg(quality),
        "course_avg_difficulty":   _avg(diff),
        "course_would_take_again": wta_pct,
        "course_num_ratings":      len(course_ratings),
        "overall_avg_rating":      node.get("avgRating"),
        "overall_avg_difficulty":  node.get("avgDifficulty"),
        "overall_would_take_again": overall_wta if overall_wta not in (None, -1) else None,
        "overall_num_ratings":     node.get("numRatings"),
    }
