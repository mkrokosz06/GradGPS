"""
GET  /programs/all               — return all program names (cached in memory after first call)
GET  /programs/search?q=forensic — filter cached list, case-insensitive substring match
POST /programs/select            — save a user's major selection
"""

import json
import os
import re

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from boto3.dynamodb.conditions import Key

import credential_catalog
from db import requirements_table, users_table
from deps import get_user_id

router = APIRouter()

# ── University Park scoping ──────────────────────────────────────────────────
# This app is University Park (main campus) only.  Program names carry a
# parenthetical qualifier ONLY to disambiguate an offering that exists at more
# than one campus (e.g. "Accounting, B.S. (Business)" at UP vs
# "Accounting, B.S. (Capital)" at Harrisburg).  The large majority of programs
# have NO parenthetical at all and are UP by default — so this MUST stay a
# denylist of non-UP campuses, not an allowlist of UP colleges (an allowlist
# would wrongly drop every unqualified program).
#
# The campus list is kept EXHAUSTIVE — every Commonwealth/branch campus and its
# common aliases, not just the ones currently in the catalog — so a future
# re-scrape can't silently leak a campus we forgot to list.  `is_up_program()`
# is the single authoritative definition of "a University Park program"; the SAP
# scraper (see docs/timeline-sap-hybrid.md) imports it so the app and the
# template set agree on exactly which majors are in scope.
_NON_UP_CAMPUS_KEYWORDS = {
    "abington", "altoona", "beaver", "berks", "brandywine", "dubois", "du bois",
    "erie", "behrend", "fayette", "greater allegheny", "harrisburg", "capital",
    "hazleton", "lehigh valley", "mont alto", "new kensington", "schuylkill",
    "scranton", "worthington scranton", "shenango", "wilkes-barre", "york",
    "great valley", "university college", "world campus", "commonwealth",
}

# The resident-instruction colleges at University Park.  A parenthetical drawn
# from this set positively means UP.  Not used to filter (unqualified programs
# have no college either) — it's the authoritative allowlist the SAP scraper
# validates college paths against, and lets us assert a parenthetical is a known
# college rather than an unrecognised (possibly new-campus) surprise.
_UP_COLLEGE_QUALIFIERS = {
    "agricultural sciences", "arts and architecture", "business",
    "communications", "earth and mineral sciences", "education", "engineering",
    "health and human development", "information sciences and technology",
    "intercollege", "liberal arts", "nursing", "science", "k-12",
}


# The name test alone isn't enough: most branch-campus programs carry no campus
# parenthetical ("Law and Society, B.A." is Abington-only, "Engineering, B.S." is
# Behrend), and 41 of them leaked into the major picker.  The bulletin's program
# index tags each entry with its campuses, so `scripts/scrape_program_campuses.py`
# records every degree program it lists WITHOUT University Park.  Still a
# denylist — a name the file doesn't mention is kept — and a missing/unreadable
# file degrades to the name test rather than failing startup.
_NON_UP_PROGRAMS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "program_data", "non_up_programs.json",
)


def _load_non_up_programs() -> frozenset[str]:
    try:
        with open(_NON_UP_PROGRAMS_PATH, encoding="utf-8") as f:
            return frozenset(json.load(f)["non_up_programs"])
    except (OSError, ValueError, KeyError):
        return frozenset()


_NON_UP_PROGRAMS = _load_non_up_programs()


def is_up_program(name: str) -> bool:
    """Whether a program is offered at University Park (this app's only scope).

    Drops a program the bulletin lists only at other campuses, or whose name
    carries a non-UP campus parenthetical.  Everything else is kept, so an
    unknown name fails open.  This is the shared UP-scope definition used by
    the program list and the SAP / entrance-to-major scrapers.
    """
    if name in _NON_UP_PROGRAMS:
        return False
    nl = name.lower()
    return not any(
        f"({kw})" in nl or f"({kw} " in nl for kw in _NON_UP_CAMPUS_KEYWORDS
    )


# ── Degree-program scoping ───────────────────────────────────────────────────
# The scraped catalog carries minors and certificates alongside degree majors
# (197 minors, ~30 certificates).  They are NOT selectable yet: the app models
# exactly one program per student — `run_audit()` audits a single
# `program_name`, and the timeline is built from that one audit — so a student
# who picked "Psychology, Minor" as their major would get an audit against 18
# credits and read as nearly graduated.  Until minors/certificates are modelled
# as their own thing (a separate field + a second audit pass), keep them out of
# the picker entirely.
_NON_DEGREE_TYPES = {"minor", "certificate"}

# Belt-and-braces: catalog rows written outside load_catalog.py may lack the
# `degree` attribute, but PSU program names carry the qualifier themselves.
_NON_DEGREE_NAME_RE = re.compile(r",\s*(minor|certificate)\b", re.I)


def is_degree_program(name: str, degrees: set[str]) -> bool:
    """Whether a catalog program is a degree major (vs. a minor/certificate).

    `degrees` is every non-empty `degree` value seen on that program's rows.
    A program is dropped only when it is positively identified as non-degree
    and nothing claims otherwise — an unlabelled program (1681 catalog rows
    have a blank degree) stays in, which is the fail-safe direction.
    """
    if _NON_DEGREE_NAME_RE.search(name):
        return False
    lowered = {d.strip().lower() for d in degrees if d and d.strip()}
    if not lowered:
        return True
    return not lowered <= _NON_DEGREE_TYPES


# In-memory cache populated on first request — avoids a 10-page DynamoDB scan per search
_programs_cache: list[str] | None = None


def _load_all_programs() -> list[str]:
    global _programs_cache
    if _programs_cache is not None:
        return _programs_cache
    degrees_by_name: dict[str, set[str]] = {}
    # "degree" is a DynamoDB reserved word — must go through an expression name.
    scan_kwargs: dict = {
        "ProjectionExpression": "program_name, #deg",
        "ExpressionAttributeNames": {"#deg": "degree"},
    }
    while True:
        resp = requirements_table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            degrees_by_name.setdefault(item["program_name"], set()).add(
                item.get("degree") or ""
            )
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        scan_kwargs["ExclusiveStartKey"] = last
    # Exclude sentinel rows (__GEN_ED__, __CROSSLISTINGS__), non-UP programs,
    # and non-degree programs (minors/certificates)
    _programs_cache = sorted(
        n for n, degs in degrees_by_name.items()
        if not n.startswith("__") and is_up_program(n) and is_degree_program(n, degs)
    )
    return _programs_cache


@router.get("/all")
def get_all_programs():
    """Return every distinct program name — used by the mobile app to populate the full list."""
    names = _load_all_programs()
    return {"results": names, "count": len(names)}


@router.get("/search")
def search_programs(q: str = Query(..., min_length=1)):
    """Case-insensitive substring search over the cached program list."""
    q_lower = q.lower()
    names = [n for n in _load_all_programs() if q_lower in n.lower()]
    return {"results": names, "count": len(names)}


@router.get("/credentials")
def search_credentials(q: str | None = Query(None)):
    """Minors and certificates a student can declare (see credential_catalog.py).

    Deliberately a *separate* endpoint from the major list: a credential is declared
    alongside a major, not instead of one, and `/programs/all` must keep returning only
    degree programs so an older mobile build can never put a minor in the major slot.
    """
    results = credential_catalog.list_credentials(q)
    return {"results": results, "count": len(results)}


class SelectMajorBody(BaseModel):
    major:   str
    subplan: str | None = None   # e.g. "Forensic Chemistry" — optional at selection time


@router.post("/select")
def select_major(
    body: SelectMajorBody,
    user_id: str = Depends(get_user_id),
):
    """Save the student's chosen major (and optional subplan) to their user record."""
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(body.major),
        Limit=1,
    )
    if not resp.get("Items"):
        raise HTTPException(status_code=404, detail=f"Major not found: {body.major}")

    # Minors/certificates are in the catalog but not selectable as a major (see
    # _NON_DEGREE_TYPES).  The picker already hides them, but an older mobile
    # build could still post one, so refuse it here too.
    if not is_degree_program(body.major, {r.get("degree") or "" for r in resp["Items"]}):
        raise HTTPException(
            status_code=400,
            detail=f"{body.major} is a minor or certificate, not a degree program. "
                   "GradGPS doesn't support these yet — pick your degree major.",
        )

    # Validate subplan actually exists in the requirement groups for this major
    # before persisting it, so a stale subplan from a previous major can't leak.
    effective_subplan = None
    if body.subplan:
        all_rows_resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(body.major),
            ProjectionExpression="requirement_group",
        )
        all_group_names = {r.get("requirement_group", "").lower() for r in all_rows_resp.get("Items", [])}
        if any(body.subplan.lower() in g for g in all_group_names):
            effective_subplan = body.subplan

    # An Application Focus belongs to one major: a new major starts without one.
    previous = (users_table.get_item(Key={"user_id": user_id}).get("Item") or {}).get("major")
    drop_focus = ", focus" if previous and previous != body.major else ""
    if effective_subplan:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET major = :m, subplan = :s" + (" REMOVE focus" if drop_focus else ""),
            ExpressionAttributeValues={":m": body.major, ":s": effective_subplan},
        )
    else:
        users_table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET major = :m REMOVE subplan" + drop_focus,
            ExpressionAttributeValues={":m": body.major},
        )

    return {"status": "ok", "major": body.major, "subplan": effective_subplan}


def focus_areas(major: str) -> list[dict]:
    """A major's Application Focus areas, from the catalog's per-area pools
    (scrape_psu tags each with `focus_area`): [{name, credits, courses}]. Empty
    for a major without one."""
    from boto3.dynamodb.conditions import Key
    rows, kw = [], {"KeyConditionExpression": Key("program_name").eq(major)}
    while True:
        r = requirements_table.query(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    areas: dict[str, dict] = {}
    for r in rows:
        name = r.get("focus_area")
        if not name or name == "*":
            continue
        a = areas.setdefault(name, {"name": name, "credits": float(r.get("group_threshold") or 0),
                                    "courses": []})
        if r["course_code"] not in a["courses"]:
            a["courses"].append(r["course_code"])
    return list(areas.values())


@router.get("/focus-areas")
def get_focus_areas(major: str):
    """The Application Focus areas a student of `major` chooses between (ETI,
    Data Sciences, HCDD, Cybersecurity, IT Ethics). An empty list means the major
    has none and the app shows nothing."""
    return {"major": major, "areas": focus_areas(major)}
