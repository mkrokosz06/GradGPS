"""
RateMyProfessors GraphQL client.

Hits the unofficial RMP GraphQL endpoint to:
  1. Search professors by name at a given school
  2. Fetch ratings filtered to a specific course code and compute course-specific averages

Penn State University Park school ID: U2Nob29sLTEzOTk= (base64 of "School-1399")
"""

import re
import httpx
from datetime import date

RMP_GRAPHQL = "https://www.ratemyprofessors.com/graphql"
PSU_SCHOOL_ID = "U2Nob29sLTc1OA=="  # School-758 = Penn State University (State College, PA)


# ── PSU term helpers ──────────────────────────────────────────────────────────

def _upcoming_terms() -> list[str]:
    """
    Return PSU term codes for the current + next semester, most relevant first.
    PSU term format: YYYYMM  (01=Spring, 06=Summer, 09=Fall)
    """
    today = date.today()
    year, month = today.year, today.month
    terms: list[str] = []

    if month <= 5:  # Jan–May: currently Spring, Fall is next
        terms = [f"{year}01", f"{year}09"]
    elif month <= 8:  # Jun–Aug: currently Summer, Fall is next
        terms = [f"{year}09", f"{year}01"]
    else:  # Sep–Dec: currently Fall, Spring is next
        terms = [f"{year}09", f"{year + 1}01"]

    return terms


def _parse_code(course_code: str) -> tuple[str, str]:
    """'IST 301' -> ('IST', '301');  'MATH 140' -> ('MATH', '140')"""
    parts = course_code.strip().upper().split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    # fallback: split at first digit
    m = re.match(r"([A-Z]+)(\d.*)", course_code.strip().upper())
    if m:
        return m.group(1), m.group(2)
    return course_code.strip().upper(), ""


async def get_psu_instructors(course_code: str) -> list[str]:
    """
    Scrape Penn State's public Schedule of Courses for the upcoming terms
    and return a deduplicated list of instructor last names for this course.

    Tries both upcoming terms concurrently. Returns [] on any error so callers
    can fall back gracefully.
    """
    subject, number = _parse_code(course_code)
    if not subject or not number:
        return []

    req_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }

    async def _scrape_term(term: str) -> list[str]:
        url = (
            "https://schedule.psu.edu/"
            f"?campus=UP&term={term}&subject={subject}&courseNumber={number}"
        )
        try:
            async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
                resp = await client.get(url, headers=req_headers)
            html = resp.text

            names: list[str] = []
            # Pattern 1: <td class="instructor">Last, First</td>
            names += re.findall(
                r'class="[^"]*instructor[^"]*"[^>]*>\s*([A-Z][A-Za-z\-\']+(?:,\s*[A-Z][A-Za-z\-\']+)?)\s*<',
                html,
            )
            # Pattern 2: "Instructor: Last, First" free text
            names += re.findall(
                r'[Ii]nstructor[:\s]+([A-Z][A-Za-z\-\']+(?:,\s*[A-Z][A-Za-z\-\']+)?)',
                html,
            )

            last_names: list[str] = []
            for n in names:
                if "," in n:
                    last_names.append(n.split(",")[0].strip())
                else:
                    parts = n.strip().split()
                    last_names.append(parts[-1] if parts else n.strip())

            return list(dict.fromkeys(ln for ln in last_names if ln))
        except Exception:
            return []

    # Run both terms concurrently — take first non-empty result
    import asyncio
    results = await asyncio.gather(*[_scrape_term(t) for t in _upcoming_terms()])
    for names in results:
        if names:
            return names
    return []

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    # RMP's GraphQL endpoint requires this basic auth header
    "Authorization": "Basic dGVzdDp0ZXN0",
    "Referer": "https://www.ratemyprofessors.com/",
    "Origin": "https://www.ratemyprofessors.com",
}


def _normalize_code(code: str) -> str:
    """'IST 301W' -> 'IST301'  (strip W/H/N suffix, collapse whitespace)"""
    code = code.strip().upper()
    code = re.sub(r"[WHN]$", "", code)
    return re.sub(r"\s+", "", code)


async def search_professor(name: str, school_id: str = PSU_SCHOOL_ID) -> list[dict]:
    """
    Return up to 5 RMP teacher matches for `name` at the given school.
    Each result has: id, firstName, lastName, avgRating, avgDifficulty,
                     wouldTakeAgainPercent, numRatings, department
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
        "variables": {
            "query": {"text": name, "schoolID": school_id},
        },
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


async def get_course_ratings(teacher_id: str, course_code: str) -> dict:
    """
    Fetch ratings for a teacher filtered to a specific course code.

    RMP's courseFilter param does string matching against what students typed,
    so we also do our own normalized comparison to catch "IST301", "ist 301", etc.

    Returns:
      course_avg_rating, course_avg_difficulty, course_would_take_again (%),
      course_num_ratings  — all computed from course-specific ratings only.
      overall_avg_rating, overall_avg_difficulty, overall_would_take_again,
      overall_num_ratings — from the teacher-level aggregates for context.

    wouldTakeAgain in individual ratings: 1=yes, 0=no, -1=N/A (excluded from %).
    """
    norm_target = _normalize_code(course_code)

    # Use RMP's courseFilter for server-side pre-filtering, then normalize client-side
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
        "variables": {
            "id": teacher_id,
            "courseFilter": course_code,  # e.g. "IST 301"
        },
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(RMP_GRAPHQL, json=body, headers=_HEADERS)
        resp.raise_for_status()

    node = resp.json().get("data", {}).get("node") or {}
    edges = node.get("ratings", {}).get("edges", [])

    # Client-side normalized filter — catches alternate capitalizations/spacing
    course_ratings = []
    for e in edges:
        r = e.get("node", {})
        raw_class = r.get("class") or ""
        if _normalize_code(raw_class) == norm_target:
            course_ratings.append(r)

    def _avg(vals: list) -> float | None:
        cleaned = [v for v in vals if v is not None]
        return round(sum(cleaned) / len(cleaned), 1) if cleaned else None

    quality = [r.get("qualityRating") for r in course_ratings]
    diff = [r.get("difficultyRatingRounded") for r in course_ratings]
    # wouldTakeAgain: 1=yes, 0=no, -1=N/A — exclude -1
    wta_vals = [r.get("wouldTakeAgain") for r in course_ratings if r.get("wouldTakeAgain", -1) != -1]
    wta_pct = round(sum(wta_vals) / len(wta_vals) * 100) if wta_vals else None

    return {
        "course_avg_rating": _avg(quality),
        "course_avg_difficulty": _avg(diff),
        "course_would_take_again": wta_pct,
        "course_num_ratings": len(course_ratings),
        "overall_avg_rating": node.get("avgRating"),
        "overall_avg_difficulty": node.get("avgDifficulty"),
        # RMP uses -1 to mean "no data" — normalise to None
        "overall_would_take_again": (
            node["wouldTakeAgainPercent"]
            if node.get("wouldTakeAgainPercent") not in (None, -1)
            else None
        ),
        "overall_num_ratings": node.get("numRatings"),
    }
