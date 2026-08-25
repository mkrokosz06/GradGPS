"""
GET /courses/{code}                        — course metadata + PSU bulletin description
GET /courses/{code}/professor?name=Smith   — RMP ratings for a professor filtered to this course
"""

import re
import asyncio
import httpx

from fastapi import APIRouter, HTTPException, Query, Depends
from boto3.dynamodb.conditions import Attr, Key

from db import requirements_table
from deps import get_user_id
import rmp_client

router = APIRouter()

# ── In-memory cache: course_code -> {course_title, credits} ──────────────────
# Avoids re-scanning the 31k-row requirements table on every tap.
_course_cache: dict[str, dict] = {}

# ── Gen-ed course cache: for the class-selector "search for a class" picker ──
# The eight choose_credits domain/culture pools under __GEN_ED__ hold every
# course that satisfies a gen-ed category. We load them once (they change rarely)
# into a category-token → [courses] map plus an all-gen-ed union, so a slot's
# candidate list is a cheap in-memory lookup + substring filter.
_gen_ed_by_cat: dict[str, list[dict]] | None = None
_gen_ed_all: list[dict] | None = None


def _cat_token(group_name: str) -> str:
    """'US: United States Cultures' -> 'US'; 'GN: Natural Sciences' -> 'GN'."""
    return (group_name or "").split(":")[0].strip().upper().split(" ")[0] if group_name else ""


def _load_gen_ed() -> None:
    global _gen_ed_by_cat, _gen_ed_all
    if _gen_ed_by_cat is not None:
        return
    rows: list[dict] = []
    resp = requirements_table.query(KeyConditionExpression=Key("program_name").eq("__GEN_ED__"))
    rows.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq("__GEN_ED__"),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        rows.extend(resp.get("Items", []))

    by_cat: dict[str, dict[str, dict]] = {}   # cat -> code(upper) -> course (deduped)
    all_map: dict[str, dict] = {}
    for r in rows:
        # Only the searchable domain/culture pools — skip the fixed Communication
        # choose_one groups (bounded options) and the WAC rule row.
        if r.get("group_type") != "choose_credits":
            continue
        code = (r.get("course_code") or "").strip()
        if not code:
            continue
        cat = _cat_token(r.get("requirement_group", ""))
        course = {
            "course_code":    code,
            "course_title":   r.get("course_title", ""),
            "credits":        float(r.get("credits", 3) or 3),
            "multi_category": bool(r.get("multi_category", False)),
        }
        by_cat.setdefault(cat, {})[code.upper()] = course
        all_map[code.upper()] = course

    _gen_ed_by_cat = {c: list(m.values()) for c, m in by_cat.items()}
    _gen_ed_all = list(all_map.values())


def _resolve_slot_universe(slot_key: str) -> list[dict]:
    """Candidate courses that can fill a slot. v1: gen-ed slots only.
    'gened:US' -> that category; 'gened:GENERAL#sN' -> all gen-ed courses."""
    if not slot_key.startswith("gened:"):
        return []
    _load_gen_ed()
    token = slot_key[len("gened:"):].split("#")[0].strip().upper()
    if token == "GENERAL":
        return _gen_ed_all or []
    return (_gen_ed_by_cat or {}).get(token, [])


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
# NOTE: /for-slot MUST be declared before /{code}, else FastAPI matches it as a
# course code ("for-slot").

@router.get("/for-slot")
def courses_for_slot(
    slot_key: str = Query(..., description="The class-selector slot_key, e.g. 'gened:US'"),
    q: str | None = Query(None, description="Substring filter over code + title"),
    limit: int = Query(40, ge=1, le=200),
    user_id: str = Depends(get_user_id),
):
    """Candidate courses a student can search to fill a slot. v1: gen-ed slots
    only (named category or generic). Non-gen-ed slots return an empty list.

    A large universe (generic 'any gen-ed') returns `needs_query: true` on an
    empty `q` so the UI prompts the user to type instead of shipping ~3.9k rows.
    """
    universe = _resolve_slot_universe(slot_key)
    ql = (q or "").strip().lower()

    if not ql:
        if len(universe) > 200:
            return {"results": [], "needs_query": True}
        results = sorted(universe, key=lambda c: c["course_code"])
        return {"results": results, "needs_query": False}

    hits = [
        c for c in universe
        if ql in c["course_code"].lower() or ql in c["course_title"].lower()
    ]
    # Prefix matches on the code first (e.g. "soc" → SOC 119 before a title hit).
    hits.sort(key=lambda c: (not c["course_code"].lower().startswith(ql), c["course_code"]))
    return {"results": hits[:limit], "needs_query": False}


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
