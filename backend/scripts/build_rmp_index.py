"""
build_rmp_index.py — One-time script to build a RateMyProfessors reverse index
for Penn State professors into DynamoDB table `rmp_professor_courses`.

Usage:
    python scripts/build_rmp_index.py

Table written: rmp_professor_courses
  PK: course_code  (e.g. "MATH 140")
  SK: professor_id (e.g. "VGVhY2hlci0x")
  Attributes: name, department, overall_avg_rating, overall_num_ratings
"""

import asyncio
import re
import sys
import os
from decimal import Decimal, InvalidOperation

import httpx

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from db import get_dynamodb

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHOOL_ID = "U2Nob29sLTc1OA=="   # Penn State (School-758)
RMP_GRAPHQL = "https://www.ratemyprofessors.com/graphql"
TABLE_NAME  = "rmp_professor_courses"

HEADERS = {
    "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type":  "application/json",
    "Authorization": "Basic dGVzdDp0ZXN0",
    "Referer":       "https://www.ratemyprofessors.com/",
    "Origin":        "https://www.ratemyprofessors.com",
}

# ---------------------------------------------------------------------------
# Course code normalisation
# ---------------------------------------------------------------------------

ALIASES: dict[str, str] = {
    "MAT":   "MATH",  "CALC":  "MATH",  "STA":   "STAT",  "STATS": "STAT",
    "PSYC":  "PSYCH", "BIO":   "BIOL",  "COMP":  "CMPSC", "CS":    "CMPSC",
    "ACCT":  "ACCTG", "ACC":   "ACCTG", "ECON":  "ECON",
    "MGMT":  "MGMT",  "MKTG":  "MKTG",  "FIN":   "FIN",
    "PHYS":  "PHYS",  "ENGL":  "ENGL",  "HIST":  "HIST",
    "SOC":   "SOC",   "PHIL":  "PHIL",  "GEOG":  "GEOG",
    "COMM":  "COMM",  "KINES": "KINES", "NURS":  "NURS",
    "EARTH": "GEOSC", "GEO":   "GEOSC",
}


def normalize_course_code(raw: str) -> str | None:
    """
    Convert a student-typed RMP class string to canonical PSU format "SUBJECT NUMBER".
    Returns None if the string doesn't look like a course code.

    Examples:
      "mat140"    -> "MATH 140"
      "IST301"    -> "IST 301"
      "ist 301"   -> "IST 301"
      "CMPSC 121" -> "CMPSC 121"
      "calc 2"    -> "MATH 2"
      "professor notes" -> None
    """
    if not raw or len(raw) > 20:
        return None
    s = raw.strip().upper()
    s = re.sub(r"[^A-Z0-9\s]", "", s)   # strip punctuation
    s = re.sub(r"\s+", "", s)            # collapse spaces
    # Must match: 2-6 alpha chars followed by 1-4 digits (optional letter suffix)
    m = re.match(r"^([A-Z]{2,6})(\d{1,4}[A-Z]?)$", s)
    if not m:
        return None
    subject, number = m.group(1), m.group(2)
    subject = ALIASES.get(subject, subject)
    return f"{subject} {number}"


# ---------------------------------------------------------------------------
# GraphQL queries
# ---------------------------------------------------------------------------

QUERY_ALL_TEACHERS = """
query GetAllTeachers($schoolID: ID!, $after: String) {
  search: newSearch {
    teachers(query: {text: "", schoolID: $schoolID}, first: 20, after: $after) {
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          firstName
          lastName
          department
          avgRating
          avgDifficulty
          wouldTakeAgainPercent
          numRatings
        }
      }
    }
  }
}
"""

QUERY_TEACHER_COURSES = """
query GetTeacherCourses($id: ID!) {
  node(id: $id) {
    ... on Teacher {
      ratings(first: 100) {
        edges {
          node { class }
        }
      }
    }
  }
}
"""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def _gql(client: httpx.AsyncClient, query: str, variables: dict) -> dict:
    """Execute one GraphQL request, retrying once on HTTP 429."""
    payload = {"query": query, "variables": variables}
    resp = await client.post(RMP_GRAPHQL, json=payload, headers=HEADERS, timeout=15)
    if resp.status_code == 429:
        print("  [rate-limit] sleeping 5 s then retrying …")
        await asyncio.sleep(5)
        resp = await client.post(RMP_GRAPHQL, json=payload, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


async def fetch_professor_page(
    client: httpx.AsyncClient, after: str | None
) -> tuple[list[dict], bool, str | None]:
    """
    Fetch one page of 20 professors.
    Returns (nodes, has_next_page, end_cursor).
    """
    variables: dict = {"schoolID": SCHOOL_ID}
    if after:
        variables["after"] = after

    data = await _gql(client, QUERY_ALL_TEACHERS, variables)
    teachers_data = data["data"]["search"]["teachers"]
    page_info     = teachers_data["pageInfo"]
    nodes         = [edge["node"] for edge in teachers_data["edges"]]
    return nodes, page_info["hasNextPage"], page_info.get("endCursor")


async def fetch_professor_courses(client: httpx.AsyncClient, prof_id: str) -> set[str]:
    """
    Fetch up to 20 ratings for a professor and return the set of
    normalised course codes found therein.
    """
    data = await _gql(client, QUERY_TEACHER_COURSES, {"id": prof_id})
    node = data["data"].get("node") or {}
    ratings = node.get("ratings") or {}
    edges   = ratings.get("edges") or []
    codes: set[str] = set()
    for edge in edges:
        raw = (edge.get("node") or {}).get("class") or ""
        code = normalize_course_code(raw)
        if code:
            codes.add(code)
    return codes


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _to_decimal(value) -> Decimal | None:
    """Safely convert a float/int/str to Decimal for DynamoDB."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def write_professor_courses(
    table,
    prof: dict,
    course_codes: set[str],
) -> int:
    """
    Write one item per course code for this professor.
    Returns the number of items successfully written.
    """
    name       = f"{prof['firstName']} {prof['lastName']}".strip()
    department = prof.get("department") or ""
    avg_rating = _to_decimal(prof.get("avgRating"))
    num_ratings = int(prof.get("numRatings") or 0)
    prof_id    = prof["id"]

    written = 0
    for code in course_codes:
        item: dict = {
            "course_code":         code,
            "professor_id":        prof_id,
            "name":                name,
            "department":          department,
            "overall_num_ratings": num_ratings,
        }
        if avg_rating is not None:
            item["overall_avg_rating"] = avg_rating

        try:
            table.put_item(Item=item)
            written += 1
        except Exception as exc:
            print(f"  [dynamo-err] {code} / {prof_id}: {exc}")

    return written


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("Fetching all PSU professors from RateMyProfessors…")
    print(f"School ID: {SCHOOL_ID}")
    print(f"Writing to DynamoDB table: {TABLE_NAME}\n")

    db    = get_dynamodb()
    table = db.Table(TABLE_NAME)

    total_professors = 0
    total_entries    = 0
    page_num         = 0
    after: str | None = None

    async with httpx.AsyncClient() as client:
        while True:
            page_num += 1

            # --- fetch one page of professors ---
            try:
                professors, has_next, end_cursor = await fetch_professor_page(client, after)
            except Exception as exc:
                print(f"[page-err] page {page_num}: {exc} — aborting pagination")
                break

            if not professors:
                break

            # --- concurrently fetch course lists for this page ---
            async def fetch_courses_safe(prof: dict) -> tuple[dict, set[str]]:
                if (prof.get("numRatings") or 0) == 0:
                    return prof, set()
                try:
                    codes = await fetch_professor_courses(client, prof["id"])
                    return prof, codes
                except Exception as exc:
                    print(f"  [course-err] {prof['firstName']} {prof['lastName']}: {exc}")
                    return prof, set()

            results: list[tuple[dict, set[str]]] = await asyncio.gather(
                *[fetch_courses_safe(p) for p in professors]
            )

            # --- write to DynamoDB ---
            for prof, codes in results:
                if not codes:
                    continue
                written = write_professor_courses(table, prof, codes)
                total_entries += written

            total_professors += len(professors)

            if page_num % 5 == 0:
                print(
                    f"  [progress] page {page_num} | professors so far: {total_professors}"
                    f" | pairs written: {total_entries}"
                )

            if not has_next:
                break

            after = end_cursor
            await asyncio.sleep(0.3)  # be polite to the RMP servers

    print(
        f"\nDone. Indexed {total_entries} professor-course pairs"
        f" across {total_professors} professors."
    )


if __name__ == "__main__":
    asyncio.run(main())
