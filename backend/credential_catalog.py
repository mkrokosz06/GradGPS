"""
Minor & certificate requirements — the credential catalog.

A *credential* is a minor or a certificate: coursework a student declares in addition to
their major.  Requirements live as one bundled JSON file under `credential_data/`, built
and verified by `credentials/scrape_credentials.py` (see that folder's README), and
`load_credential()` is the single entry point.

**Why a bundled file instead of the `requirements` table.**  Same reasoning as
`sap_templates/` + `plan_templates.py`:

  * `run_audit()` is pure — it takes a list of requirement-row dicts, not a table handle,
    so nothing has to live in DynamoDB for a credential to be audited;
  * prod DynamoDB IAM is per-table scoped, so a table-backed catalog needs an infra change
    plus a seeding run against prod for every data refresh, while a bundled file ships in
    the container image on a normal deploy;
  * the JSON diffs in git, so a re-scrape is a reviewable PR rather than an opaque write.

The `requirements` table does still hold credential rows from the original `load_catalog.py`
import, but they are the broken ones this catalog replaces (see docs/minors-certificates.md)
and nothing queries them once credentials are read from here.

**Accuracy.**  Every credential in the file was checked against PSU's own published credit
total; 204 of the 205 that publish one agree.  `scrape_credentials.py --report` reprints
that figure, so a PSU page edit that breaks a parse shows up as a drop in the number
rather than as a wrong plan in a student's timeline.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "credential_data",
    "credential_requirements.json",
)

# Credential-only group types.  The rest (required / choose_one / choose_credits /
# choose_courses) are the engine's existing vocabulary.
DEPT_CREDITS         = "dept_credits"
UNSTRUCTURED_CREDITS = "unstructured_credits"

VALID_KINDS = {"minor", "certificate"}


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict]:
    """Every supported credential, keyed by program_name."""
    if not os.path.isfile(_PATH):
        return {}
    with open(_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    return {
        entry["program_name"]: entry
        for entry in payload.get("credentials", [])
        if entry.get("supported")
    }


def list_credentials(query: str | None = None) -> list[dict]:
    """Declarable credentials, newest catalog build, optionally substring-filtered.

    Summary rows only — the requirement groups are large and the picker doesn't need them.
    `manual_credits` is how many credits the bulletin defers to an adviser, so the UI can
    say so up front rather than surprising the student later.
    """
    q = (query or "").strip().lower()
    out = []
    for entry in _catalog().values():
        if q and q not in entry["program_name"].lower():
            continue
        out.append({
            "program_name":   entry["program_name"],
            "kind":           entry["kind"],
            "college":        entry.get("college", ""),
            "credits":        entry.get("credits", {}),
            "manual_credits": entry.get("manual_credits", 0),
        })
    return sorted(out, key=lambda e: e["program_name"])


def get_credential(program_name: str) -> dict | None:
    """The raw catalog entry, or None if it isn't a supported credential."""
    return _catalog().get(program_name)


def is_credential(program_name: str) -> bool:
    return program_name in _catalog()


def _pool_row(entry_name: str, group: dict, code: str) -> dict:
    """A single sentinel row standing for a whole pool.

    Pools that aren't a course list (`dept_credits`, `unstructured_credits`) still have to
    reach the engine as a *row*, because `run_audit()` groups rows.  The sentinel carries
    the rule on itself; `course_code` follows the `__GEN_ED__` / `__APP_CONFIG__` sentinel
    convention already used elsewhere and never reaches the UI, which renders pools from
    the group name.
    """
    spec = group.get("pool") or {}
    row = {
        "program_name":      entry_name,
        "requirement_group": group["name"],
        "group_type":        group["group_type"],
        "group_threshold":   group.get("threshold"),
        "course_code":       code,
        "course_title":      spec.get("text", ""),
        "credits":           group.get("threshold"),
        "min_grade":         group.get("min_grade", ""),
        "pair_group_id":     None,
        "pool_text":         spec.get("text", ""),
    }
    for key in ("dept", "depts", "min_level", "max_level",
                "sub_level", "sub_credits", "exclude"):
        if spec.get(key) not in (None, [], ""):
            row[key] = spec[key]
    return row


def to_requirement_rows(entry: dict) -> list[dict]:
    """Convert a catalog entry into the requirement-row shape `run_audit()` consumes.

    Keys match what the `requirements` table yields, so the engine cannot tell the
    difference between a credential and a major.
    """
    rows: list[dict] = []
    name = entry["program_name"]

    # Every course the credential names explicitly, anywhere.  A departmental pool is
    # "Select 11 credits … in PSYCH" on top of the *prescribed* PSYCH courses — so a
    # course that already fills a named requirement must not also fill the pool, or a
    # student who took only the two prescribed courses plus one elective would read as
    # done.  PSU's word for the pool is "Additional".
    named_codes = [
        c["course_code"]
        for g in entry.get("groups", [])
        if g["group_type"] not in (DEPT_CREDITS, UNSTRUCTURED_CREDITS)
        for c in g.get("courses", [])
    ]

    for gi, group in enumerate(entry.get("groups", [])):
        gtype = group["group_type"]

        if gtype in (DEPT_CREDITS, UNSTRUCTURED_CREDITS):
            subject = (group.get("pool") or {}).get("dept") or "ANY"
            row = _pool_row(name, group, f"__{gtype.upper()}_{subject}_{gi}__")
            if named_codes:
                row["exclude"] = sorted(set(row.get("exclude", [])) | set(named_codes))
            rows.append(row)
            continue

        for course in group.get("courses", []):
            row = {
                "program_name":      name,
                "requirement_group": group["name"],
                "group_type":        gtype,
                "group_threshold":   group.get("threshold"),
                "course_code":       course["course_code"],
                "course_title":      course.get("course_title", ""),
                "credits":           course.get("credits"),
                "min_grade":         group.get("min_grade", ""),
                "pair_group_id":     course.get("pair_group_id"),
            }
            if course.get("co_requisites"):
                row["co_requisites"] = course["co_requisites"]

            alternates = course.get("cross_listed") or []
            if alternates:
                row["cross_listed"] = alternates

            # A cross-listed course is ONE course under several subjects
            # ("AFAM/WMNST 101N"), and the student may have taken it under either.
            if alternates and gtype in ("required", "choose_one"):
                # Named requirements: pair the subjects so either one satisfies the
                # slot.  `_eval_choose_one` counts a pair as a single requirement, so
                # this credits the student without inventing an extra course.
                pair_id = row["pair_group_id"] or f"xl:{name}:{gi}:{course['course_code']}"
                row["pair_group_id"] = pair_id
                row["group_type"]    = "choose_one"
                rows.append(row)
                for alt in alternates:
                    rows.append({**row, "course_code": alt, "pair_group_id": pair_id})
            else:
                # Inside a credit pool, emitting the alternates as extra rows would
                # double-count: `_eval_choose_credits` sums per row, and `_build_taken`
                # already registers cross-listing aliases, so both codes would resolve
                # to the same transcript entry.  Emit the primary only and let that
                # existing equivalence credit a student who took the alternate.
                rows.append(row)

    return rows


def load_credential(program_name: str) -> tuple[dict, list[dict]] | None:
    """(metadata, requirement rows) for a declared credential, or None if unknown."""
    entry = get_credential(program_name)
    if entry is None:
        return None
    meta = {
        "program_name":   entry["program_name"],
        "kind":           entry["kind"],
        "college":        entry.get("college", ""),
        "credits":        entry.get("credits", {}),
        "manual_credits": entry.get("manual_credits", 0),
        "url":            entry.get("url", ""),
    }
    return meta, to_requirement_rows(entry)
