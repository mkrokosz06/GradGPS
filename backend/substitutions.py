"""
Course substitutions — "this class I took counts for that requirement".

The advisor workaround this replaces: a student takes a course that their
department accepts in place of a requirement (Connor took ESC 120 "Design for
Failure", which his adviser counts for CHE 100), but the catalog only knows the
requirement's own code, so GradGPS keeps telling him to take CHE 100 and the
timeline schedules a phantom course.

A substitution is nothing more than a **per-user course equivalence**: exactly
the same shape as the built-in `_EQUIVALENCE_PAIRS` in `audit_engine` (IST→ETI
renames, cross-listings, first-year seminars), but declared by one student for
one requirement.  So it is applied at the same choke point — the taken-set — and
every downstream consumer (major audit, gen-ed audit, timeline, home dashboard,
SAP template matcher) inherits it with no extra wiring, just as a catalog
equivalence does.

Storage reuses the `user_course_choices` table under a `sub:` slot_key namespace
rather than adding a table: prod DynamoDB IAM is per-table scoped, so a new table
needs an infra change before it can be written, and a substitution is the same
kind of thing the table already holds (a student's decision about their own plan).
`routers/user_choices.get_user_choices()` skips this namespace.

Trust model: substitutions are self-declared, so they are capped, must name a
course actually on the student's transcript, and are surfaced in the UI as the
student's own declaration — not as something GradGPS verified.
"""

import re
import logging
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key as DKey

from db import user_choices_table

logger = logging.getLogger(__name__)

SLOT_PREFIX = "sub:"
SLOT_KIND = "substitution"

# A student who needs more than this many hand-declared substitutions has a
# catalog problem, not a substitution problem — cap it so the feature can't be
# used to mark a whole degree complete.
MAX_PER_USER = 20

# "CHE 100", "CAS 100A", "ME 101", "PSU 16" — a subject prefix and a number,
# optionally one trailing attribute/section letter.
_CODE_RE = re.compile(r"^[A-Z]{2,8} \d{1,4}[A-Z]?$")


def norm_code(code: str) -> str:
    """Canonical form for a course code: upper-cased, single-spaced."""
    return re.sub(r"\s+", " ", (code or "").strip().upper())


def is_valid_code(code: str) -> bool:
    return bool(_CODE_RE.match(code))


def _key(requirement_code: str) -> str:
    return f"{SLOT_PREFIX}{requirement_code}"


def get_substitutions(user_id: str) -> dict[str, str]:
    """
    The caller's declared substitutions as `requirement_code -> substitute_course`
    (both normalized).  A missing/unreachable table must never break an audit or
    a timeline, so any failure degrades to "no substitutions" — the same
    fail-open contract `get_user_choices()` uses.
    """
    return {
        r["requirement_code"]: r["substitute_course"]
        for r in list_substitutions(user_id)
    }


def list_substitutions(user_id: str) -> list[dict]:
    """Full rows (requirement_code, substitute_course, created_at), sorted by code."""
    kwargs = {
        "KeyConditionExpression": DKey("user_id").eq(user_id)
        & DKey("slot_key").begins_with(SLOT_PREFIX),
    }
    try:
        resp = user_choices_table.query(**kwargs)
        items = list(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = user_choices_table.query(
                **kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"]
            )
            items.extend(resp.get("Items", []))
    except Exception:
        logger.warning(
            "course substitutions unavailable; treating as none", exc_info=True
        )
        return []

    rows = []
    for it in items:
        req = norm_code(it.get("requirement_code", ""))
        sub = norm_code(it.get("substitute_course", ""))
        if req and sub:
            rows.append({
                "requirement_code": req,
                "substitute_course": sub,
                "created_at": it.get("created_at", ""),
            })
    return sorted(rows, key=lambda r: r["requirement_code"])


def put_substitution(user_id: str, requirement_code: str, substitute_course: str) -> None:
    user_choices_table.put_item(Item={
        "user_id":           user_id,
        "slot_key":          _key(requirement_code),
        "slot_kind":         SLOT_KIND,
        "requirement_code":  requirement_code,
        "substitute_course": substitute_course,
        "created_at":        datetime.now(timezone.utc).isoformat(),
    })


def delete_substitution(user_id: str, requirement_code: str) -> None:
    user_choices_table.delete_item(
        Key={"user_id": user_id, "slot_key": _key(requirement_code)}
    )
