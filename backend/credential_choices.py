"""
Student-confirmed credential requirements — "these are the courses I'm using for it".

Some PSU minors state a requirement the bulletin never resolves into a course list:

    Select 5-6 credits in consultation with an adviser
    Select 6 credits from an approved list of supporting courses
    Students must take 9 credits within one or more of the following areas of
    concentration: Ceramics, Drawing and Painting, New Media, Sculpture …

There is no rule to evaluate, so `audit_engine._eval_unstructured_credits()` never
satisfies one on its own — inventing a rule would tell a student they had finished a
minor they had not.  53 of the 207 credentials carry at least one (median 6 credits),
and without this module those credentials can never read as complete no matter what
the student takes.

So the student says which courses they used.  That is the same trust model as
`substitutions.py`: self-declared, capped, and limited to courses actually on their
transcript, surfaced in the UI as the student's own claim rather than something
GradGPS verified.  Requiring a transcript course is what keeps the credit total
honest — we count real earned credits, never a guess about a course they might take.

Storage reuses the `user_course_choices` table under a `cred:` slot_key namespace,
for the same reason substitutions use `sub:`: prod DynamoDB IAM is per-table scoped,
so a new table needs an infra change first, and this is the same kind of row the
table already holds (a student's decision about their own plan).
`routers/user_choices.get_user_choices()` skips both namespaces.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key as DKey

from db import user_choices_table
from substitutions import norm_code, is_valid_code

logger = logging.getLogger(__name__)

SLOT_PREFIX = "cred:"
SLOT_KIND = "credential_requirement"

# One student cannot need more than this many hand-declared courses across every
# credential; the cap keeps the feature from being used to mark a minor complete
# without doing the work.
MAX_PER_USER = 30

# `program|group|course` — none of the three may contain the separator, and PSU
# program/group names never do.
_SEP = "|"


def slot_key(program: str, group: str, course_code: str) -> str:
    """One row per attested course, so a requirement can hold several."""
    return f"{SLOT_PREFIX}{program}{_SEP}{group}{_SEP}{norm_code(course_code)}"


def _parse_key(key: str) -> tuple[str, str, str] | None:
    if not key.startswith(SLOT_PREFIX):
        return None
    parts = key[len(SLOT_PREFIX):].split(_SEP)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def group_key(program: str, group: str) -> str:
    """How a requirement is addressed in the map `get_credential_choices` returns."""
    return f"{program}{_SEP}{group}"


def get_credential_choices(user_id: str) -> dict[str, list[str]]:
    """Every course the student has attested, keyed by `program|group`.

    A missing table must never break the audit — degrade to "nothing attested",
    exactly as `get_user_choices` does.
    """
    kwargs = {"KeyConditionExpression": DKey("user_id").eq(user_id)}
    try:
        resp = user_choices_table.query(**kwargs)
        items = list(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = user_choices_table.query(**kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
            items.extend(resp.get("Items", []))
    except Exception:
        logger.warning("user_course_choices unavailable; treating as no credential choices",
                       exc_info=True)
        return {}

    out: dict[str, list[str]] = {}
    for item in items:
        parsed = _parse_key(str(item.get("slot_key", "")))
        if not parsed:
            continue
        program, group, course = parsed
        out.setdefault(group_key(program, group), []).append(course)
    return out


def for_credential(choices: dict[str, list[str]], program: str) -> dict[str, list[str]]:
    """Narrow the map to one credential, keyed by requirement group.

    This is the shape `run_audit(..., attested_by_group=...)` wants, so the engine
    never has to know which credential it is auditing.
    """
    prefix = f"{program}{_SEP}"
    return {
        key[len(prefix):]: courses
        for key, courses in choices.items()
        if key.startswith(prefix)
    }


def count_for_user(user_id: str) -> int:
    return sum(len(v) for v in get_credential_choices(user_id).values())


def add_course(user_id: str, program: str, group: str, course_code: str) -> None:
    user_choices_table.put_item(Item={
        "user_id":       user_id,
        "slot_key":      slot_key(program, group, course_code),
        "slot_kind":     SLOT_KIND,
        "chosen_course": norm_code(course_code),
        "program":       program,
        "updated_at":    datetime.now(timezone.utc).isoformat(),
    })


def remove_course(user_id: str, program: str, group: str, course_code: str) -> None:
    user_choices_table.delete_item(Key={
        "user_id":  user_id,
        "slot_key": slot_key(program, group, course_code),
    })


def remove_credential(user_id: str, program: str) -> int:
    """Drop every attested course for a credential the student just un-declared.

    Without this, re-adding the minor later would silently resurrect stale claims.
    """
    removed = 0
    for key, courses in get_credential_choices(user_id).items():
        if not key.startswith(f"{program}{_SEP}"):
            continue
        group = key.split(_SEP, 1)[1]
        for course in courses:
            remove_course(user_id, program, group, course)
            removed += 1
    return removed


__all__ = [
    "SLOT_PREFIX", "SLOT_KIND", "MAX_PER_USER",
    "slot_key", "group_key", "get_credential_choices", "for_credential",
    "count_for_user", "add_course", "remove_course", "remove_credential",
    "norm_code", "is_valid_code",
]
