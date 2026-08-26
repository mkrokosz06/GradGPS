"""
GET /courses/{code}                        — course metadata + PSU bulletin description
GET /courses/{code}/professor?name=Smith   — RMP ratings for a professor filtered to this course
"""

import re
import asyncio
import httpx

from fastapi import APIRouter, HTTPException, Query, Depends
from boto3.dynamodb.conditions import Attr, Key

from db import requirements_table, transcript_table, users_table
from deps import get_user_id
from audit_engine import run_gen_ed_audit
from sap_schedule import build_gen_ed_satisfied
import business_breadth as bb
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
_gen_ed_labels: dict[str, str] = {}      # token -> human label ("GN" -> "Natural Sciences")
_gen_ed_rows: list[dict] = []            # raw __GEN_ED__ rows, for the per-user domain audit

# Domain display order (matches the PSU bulletin grouping).
_DOMAIN_ORDER = ["GQ", "GA", "GN", "GH", "GS", "GHW", "US", "IL"]

# World-language subject codes (mirror sap_schedule._WORLD_LANGUAGE_DEPTS). A
# world-language pool slot searches every course in these departments.
_LANG_DEPTS = {
    "ARAB", "ASL", "CHNS", "FR", "GER", "GREEK", "HEBR", "IT", "JAPNS", "KOR",
    "LATIN", "PORT", "RUS", "SPAN", "UKR",
}
_lang_courses: list[dict] | None = None


def _cat_token(group_name: str) -> str:
    """'US: United States Cultures' -> 'US'; 'GN: Natural Sciences' -> 'GN'."""
    return (group_name or "").split(":")[0].strip().upper().split(" ")[0] if group_name else ""


def _cat_label(group_name: str) -> str:
    """'GN: Natural Sciences' -> 'Natural Sciences' (the part after the token)."""
    parts = (group_name or "").split(":", 1)
    return parts[1].strip() if len(parts) == 2 and parts[1].strip() else _cat_token(group_name)


def _load_gen_ed() -> None:
    global _gen_ed_by_cat, _gen_ed_all, _gen_ed_labels, _gen_ed_rows
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
    _gen_ed_rows = rows

    by_cat: dict[str, dict[str, dict]] = {}   # cat -> code(upper) -> course (deduped)
    all_map: dict[str, dict] = {}
    labels: dict[str, str] = {}
    for r in rows:
        # Only the searchable domain/culture pools — skip the fixed Communication
        # choose_one groups (bounded options) and the WAC rule row.
        if r.get("group_type") != "choose_credits":
            continue
        code = (r.get("course_code") or "").strip()
        if not code:
            continue
        grp = r.get("requirement_group", "")
        cat = _cat_token(grp)
        labels.setdefault(cat, _cat_label(grp))
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
    _gen_ed_labels = labels


def _load_lang() -> list[dict]:
    """All world-language-department courses in the catalog (from the requirements
    table), deduped by code. Loaded once and cached."""
    global _lang_courses
    if _lang_courses is not None:
        return _lang_courses
    seen: dict[str, dict] = {}
    scan_kwargs = {"ProjectionExpression": "course_code, course_title, credits"}
    while True:
        resp = requirements_table.scan(**scan_kwargs)
        for it in resp.get("Items", []):
            code = (it.get("course_code") or "").strip().upper()
            dept = code.split(" ")[0] if " " in code else ""
            if dept in _LANG_DEPTS and code not in seen:
                seen[code] = {
                    "course_code":    code,
                    "course_title":   it.get("course_title", ""),
                    "credits":        float(it.get("credits", 3) or 3),
                    "multi_category": False,
                }
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        scan_kwargs["ExclusiveStartKey"] = last
    _lang_courses = list(seen.values())
    return _lang_courses


def remaining_gen_ed_domains(user_id: str) -> list[dict]:
    """The gen-ed domains this student hasn't satisfied yet, as [{code, label}]
    in bulletin order — the chips shown in the picker."""
    _load_gen_ed()
    tx = transcript_table.query(KeyConditionExpression=Key("user_id").eq(user_id)).get("Items", [])
    result = run_gen_ed_audit(_gen_ed_rows, tx) if _gen_ed_rows else {"groups": []}
    satisfied = build_gen_ed_satisfied(result)   # {token: bool}
    out = []
    for token in _DOMAIN_ORDER:
        if token in (_gen_ed_by_cat or {}) and not satisfied.get(token, False):
            out.append({"code": token, "label": _gen_ed_labels.get(token, token)})
    return out


def _user_program(user_id: str) -> str | None:
    """The student's major (program_name) — needed to exclude their own area from
    the business-breadth universe."""
    try:
        item = (users_table.get_item(Key={"user_id": user_id}).get("Item")) or {}
    except Exception:
        return None
    return item.get("major")


def _breadth_courses(program_name: str | None, area: str | None) -> list[dict]:
    """Business-breadth candidates in the picker's shape. With `area`, just that
    area's two-piece-sequence courses; else every breadth course available to the
    program (own major area excluded)."""
    src = bb.area_courses(area) if area else bb.all_courses(program_name)
    return [{"course_code": c["code"], "course_title": c.get("title", ""),
             "credits": 3, "area": c.get("area", area)} for c in src]


def _resolve_slot_universe(slot_key: str, category: str | None = None,
                           program_name: str | None = None) -> list[dict]:
    """Candidate courses that can fill a slot.
    - gen-ed slots: 'gened:US' -> that category; `category` overrides it so the
      student can pick a different domain; 'gened:GENERAL' / no domain -> all.
    - world-language pool slots -> every world-language-department course.
    - business-breadth pool slots -> the breadth courses for the student's program
      (own major area excluded); `category` narrows to one area.
    Anything else -> [] (not searchable in v1)."""
    if slot_key.startswith("gened:"):
        _load_gen_ed()
        token = (category or "").strip().upper() or slot_key[len("gened:"):].split("#")[0].strip().upper()
        if token in (_gen_ed_by_cat or {}):
            return _gen_ed_by_cat[token]
        return _gen_ed_all or []          # GENERAL / unknown -> whole gen-ed union
    if slot_key.startswith("pool:WORLD_LANGUAGE"):
        return _load_lang()
    if slot_key.upper().startswith("POOL:BUSINESS_BREADTH"):
        return _breadth_courses(program_name, category)
    return []


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

@router.get("/gen-ed-domains")
def gen_ed_domains(user_id: str = Depends(get_user_id)):
    """The gen-ed domains this student still needs — the picker's domain chips."""
    return {"domains": remaining_gen_ed_domains(user_id)}


@router.get("/breadth-areas")
def breadth_areas(user_id: str = Depends(get_user_id)):
    """Business-breadth areas the student can pick from (own major area excluded),
    each with its two-piece-sequence courses — the picker's area chips + courses.
    Ships the disclaimer since only some Smeal majors' lists are sourced."""
    program = _user_program(user_id)
    areas = [
        {
            "area": area,
            "structure": spec.get("structure"),
            "courses": [
                {"course_code": c["code"], "course_title": c.get("title", ""),
                 "credits": 3, "level_400": c.get("level_400", False)}
                for c in spec.get("courses", [])
            ],
        }
        for area, spec in bb.areas_for_program(program).items()
    ]
    return {"areas": areas, "disclaimer": bb.disclaimer()}


@router.get("/for-slot")
def courses_for_slot(
    slot_key: str = Query(..., description="The class-selector slot_key, e.g. 'gened:US'"),
    q: str | None = Query(None, description="Substring filter over code + title"),
    category: str | None = Query(None, description="Override the gen-ed domain to search (e.g. 'GA')"),
    limit: int = Query(500, ge=1, le=2000),
    user_id: str = Depends(get_user_id),
):
    """Candidate courses a student can search to fill a slot: gen-ed slots (any
    domain via `category`) and world-language pool slots. Other slots -> empty.

    On an empty `q` the full (domain-scoped) list is returned sorted so the UI can
    show it immediately and scroll — only an unusually huge universe (the whole
    gen-ed union, which the domain chips avoid) returns `needs_query: true`.
    """
    program = _user_program(user_id) if slot_key.upper().startswith("POOL:BUSINESS_BREADTH") else None
    universe = _resolve_slot_universe(slot_key, category, program)
    ql = (q or "").strip().lower()

    if not ql:
        # Single domains top out ~1.4k (IL); only the all-gen-ed union exceeds this,
        # and the client always picks a domain, so it never asks for the union.
        if len(universe) > 1600:
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
