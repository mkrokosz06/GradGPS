"""
GET /courses/{code}                        — course metadata + PSU bulletin description
GET /courses/{code}/professor?name=Smith   — RMP ratings for a professor filtered to this course
"""

import re
import asyncio
import httpx

from fastapi import APIRouter, HTTPException, Query
from boto3.dynamodb.conditions import Attr

from db import requirements_table
import rmp_client

router = APIRouter()

# ── In-memory cache: course_code -> {course_title, credits} ──────────────────
# Avoids re-scanning the 31k-row requirements table on every tap.
_course_cache: dict[str, dict] = {}


def _normalize_code(code: str) -> str:
    """'IST 301W' -> 'IST 301'  (strip PSU attribute suffixes only)"""
    return re.sub(r"[WHN]$", "", code.strip().upper()).strip()


async def _get_course_meta(code: str) -> dict | None:
    """Scan requirements table for the course, cache result."""
    norm = _normalize_code(code)
    if norm in _course_cache:
        return _course_cache[norm]

    # Paginated scan — stop at first match to minimise read cost
    scan_kwargs: dict = {
        "FilterExpression": Attr("course_code").eq(norm),
        "ProjectionExpression": "course_code, course_title, credits",
    }
    while True:
        resp = requirements_table.scan(**scan_kwargs)
        items = resp.get("Items", [])
        if items:
            item = items[0]
            meta = {
                "course_code": item.get("course_code", norm),
                "course_title": item.get("course_title", ""),
                "credits": int(item.get("credits", 0) or 0),
            }
            _course_cache[norm] = meta
            return meta
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        scan_kwargs["ExclusiveStartKey"] = last

    return None


async def _get_description(code: str) -> str | None:
    """
    Scrape Penn State's course bulletin for a course description.
    URL: https://bulletins.psu.edu/search/?P=IST+301
    Falls back to None on any error.
    """
    url = "https://bulletins.psu.edu/search/?P=" + code.strip().replace(" ", "+")
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GradGPS/1.0)"},
            )
        html = resp.text
        # PSU bulletin wraps descriptions in <p class="courseblockdesc">
        # Also try alternate class names used by different bulletin versions
        for pattern in [
            r'class="courseblockdesc"[^>]*>(.*?)</p>',
            r'class="cb_desc"[^>]*>(.*?)</p>',
        ]:
            m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if m:
                desc = re.sub(r"<[^>]+>", " ", m.group(1))  # strip HTML tags
                desc = re.sub(r"\s+", " ", desc).strip()
                if desc:
                    return desc
    except Exception:
        pass
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{code}")
async def get_course(code: str):
    """Return course metadata and PSU bulletin description."""
    meta = await _get_course_meta(code)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Course '{code}' not found in catalog")

    # Fire description scrape concurrently — don't block if it's slow
    description = await _get_description(code)

    return {
        **meta,
        "description": description,
    }


async def _enrich_professor(prof: dict, code: str) -> dict:
    """Fetch course-specific RMP ratings for one professor result."""
    try:
        ratings = await rmp_client.get_course_ratings(prof["id"], code)
    except Exception:
        ratings = {
            "course_avg_rating": None,
            "course_avg_difficulty": None,
            "course_would_take_again": None,
            "course_num_ratings": 0,
            "overall_avg_rating": prof.get("avgRating"),
            "overall_avg_difficulty": prof.get("avgDifficulty"),
            "overall_would_take_again": prof.get("wouldTakeAgainPercent"),
            "overall_num_ratings": prof.get("numRatings"),
        }
    return {
        "id": prof["id"],
        "name": f"{prof.get('firstName', '')} {prof.get('lastName', '')}".strip(),
        "department": prof.get("department"),
        **ratings,
    }


@router.get("/{code}/professors")
async def get_professors(code: str):
    """
    Return professors who have been rated for this course on RMP,
    looked up from the pre-built DynamoDB index (rmp_professor_courses table).
    Each result is enriched with course-specific rating aggregates.
    """
    # Step 1: index lookup — who has ratings for this course?
    index_entries = await rmp_client.get_professors_for_course(code)

    if not index_entries:
        return {"professors": [], "schedule_found": False}

    # Step 2: enrich each with course-specific rating aggregates
    async def _enrich_index_entry(entry: dict) -> dict | None:
        try:
            ratings = await rmp_client.get_course_ratings(entry["professor_id"], code)
        except Exception:
            ratings = {
                "course_avg_rating": None,
                "course_avg_difficulty": None,
                "course_would_take_again": None,
                "course_num_ratings": 0,
                "overall_avg_rating": entry.get("overall_avg_rating"),
                "overall_avg_difficulty": entry.get("overall_avg_difficulty"),
                "overall_would_take_again": None,
                "overall_num_ratings": entry.get("overall_num_ratings"),
            }
        return {
            "id": entry["professor_id"],
            "name": entry.get("name", ""),
            "department": entry.get("department"),
            **ratings,
        }

    enriched = await asyncio.gather(*[_enrich_index_entry(e) for e in index_entries])
    professors = [p for p in enriched if p is not None]

    return {"professors": professors, "schedule_found": True}


@router.get("/{code}/professor")
async def get_professor_by_name(
    code: str,
    name: str = Query(..., min_length=1, description="Professor last name or full name"),
    school_id: str = Query(None),
):
    """
    Manual fallback: search RMP by professor name and return course-specific ratings.
    Returns up to 3 best name matches.
    """
    sid = school_id or rmp_client.PSU_SCHOOL_ID

    try:
        professors = await rmp_client.search_professor(name, sid)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="RMP search request failed")

    if not professors:
        return {"professors": []}

    results = await asyncio.gather(*[_enrich_professor(p, code) for p in professors[:3]])
    return {"professors": list(results)}
