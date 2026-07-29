"""
Self-driving timeline sanity check — zero input required.

Picks N random bachelor's programs straight from the seeded catalog (default 3),
creates a throwaway fresh-student user for each (no transcript), generates their
full timeline, and asserts structural invariants that must hold for ANY major —
on both the SAP-template path and the Layer 1 credit-band packer:

  * every semester is upcoming, non-empty, and terms are unique + chronological
  * each semester's credit total matches the sum of its courses
  * academic semesters land in a sane credit band; no oversized blobs
  * no named course is scheduled twice
  * the whole plan carries enough credits for the degree (path-aware floor)

Reproducibility: the random seed is printed on every run. Re-run a failure with
  TEST_SEED=<seed> python -m pytest tests/integration/test_timeline_random_majors.py -v
Sample more majors with TEST_N_MAJORS=<n> (e.g. 180 to sweep everything).

Requires the local stack: docker-compose up + seeded tables. Skips cleanly if
DynamoDB Local isn't reachable.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/integration/test_timeline_random_majors.py -v
  * plain python:  cd backend && python tests/integration/test_timeline_random_majors.py
"""

import os
import random
import re
import socket
import sys
import uuid
from urllib.parse import urlparse

# Make the backend package importable when run as a plain script or via pytest
# from any directory (two levels up: tests/integration/ → backend/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    import pytest
except ImportError:  # plain-python mode
    pytest = None

N_MAJORS = int(os.getenv("TEST_N_MAJORS", "3"))

# Credit-band expectations. Published SAP plans occasionally run heavy (music,
# architecture studios), so the ceiling is looser than the packer's 18.
_MIN_SEM_CREDITS = 3.0    # a non-summer semester lighter than this is broken
_MAX_SEM_CREDITS = 21.0
_MIN_PLAN_SEMS   = 4      # fresh student: fewer than this means a collapsed plan
_MAX_PLAN_SEMS   = 14     # 8 academic + summers + slack; more means runaway

_SEASON_ORDER = {"SP": 0, "SU": 1, "FA": 2}


def _dynamo_reachable() -> bool:
    """Fast TCP check on DynamoDB Local so a down stack skips instead of hanging."""
    endpoint = os.getenv("DYNAMODB_ENDPOINT")
    if not endpoint:
        return True  # real AWS — let boto3 decide
    parsed = urlparse(endpoint)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 8000), timeout=2):
            return True
    except OSError:
        return False


def _term_key(term: str) -> tuple:
    parts = term.split()
    if len(parts) != 2 or parts[0] not in _SEASON_ORDER:
        return (9999, 99)
    return (int(parts[1]), _SEASON_ORDER[parts[0]])


def _norm_code(code: str) -> str:
    """Normalize a (possibly paired) course label for duplicate counting:
    'ECON 104 or ECON 102' and 'ECON 102 or ECON 104' → same key."""
    return " or ".join(sorted(p.strip().upper() for p in (code or "").split(" or ") if p.strip()))


def _template_slot_sets(template: dict | None) -> list[frozenset] | None:
    """The code-set of every named/choose-one slot in the SAP template.
    Published plans legitimately repeat slots (applied music lessons every
    semester; 'ECON 102 or ECON 104' twice meaning take one then the other),
    so the timeline may schedule a course once per matching slot."""
    if not template:
        return None
    sets: list[frozenset] = []
    for sem in template.get("semesters", []):
        for slot in sem.get("slots", []):
            if slot.get("type") == "course" and slot.get("code"):
                sets.append(frozenset({slot["code"].strip().upper()}))
            elif slot.get("type") == "choose_one" and slot.get("codes"):
                sets.append(frozenset(c.strip().upper() for c in slot["codes"]))
    return sets


def _repeat_limit(emitted_key: str, slot_sets: list[frozenset] | None) -> int:
    """How many times an emitted course label may appear in the plan: once per
    template slot that could have produced it. The matcher may emit a subset of
    a slot's options (an option consumed elsewhere is dropped), so match by
    subset, not exact label. No template (or no matching slot) → once."""
    if not slot_sets:
        return 1
    emitted = frozenset(emitted_key.split(" or "))
    return max(1, sum(1 for s in slot_sets if emitted <= s))


def _template_max_sem_credits(template: dict | None) -> float:
    """Heaviest semester the published plan itself carries (2+2 completion
    programs list 20+ credit semesters); 0 when there is no template."""
    if not template:
        return 0.0
    return max(
        (float(s.get("credits") or 0) for s in template.get("semesters", [])),
        default=0.0,
    )


def _check_timeline(major: str, tl: dict, template: dict | None) -> list[str]:
    """Return a list of invariant-violation messages (empty = healthy)."""
    problems: list[str] = []
    sems = tl.get("semesters", [])
    slot_sets = _template_slot_sets(template)
    # The band ceiling stretches to the published plan's own heaviest semester.
    band_max = max(_MAX_SEM_CREDITS, _template_max_sem_credits(template) + 0.5)

    if float(tl.get("transcript_credits") or 0) != 0:
        problems.append("fresh student reports non-zero transcript credits")

    if not (_MIN_PLAN_SEMS <= len(sems) <= _MAX_PLAN_SEMS):
        problems.append(f"{len(sems)} semesters (expected {_MIN_PLAN_SEMS}-{_MAX_PLAN_SEMS})")

    seen_terms: set[str] = set()
    course_counts: dict[str, int] = {}
    prev_key = None
    total_credits = 0.0

    for sem in sems:
        term = sem.get("term", "")
        label = f"[{term}]"

        if sem.get("status") != "upcoming":
            problems.append(f"{label} status={sem.get('status')!r}, expected 'upcoming'")
        if term in seen_terms:
            problems.append(f"{label} duplicate term")
        seen_terms.add(term)

        key = _term_key(term)
        if key == (9999, 99):
            problems.append(f"{label} unparseable term")
        elif prev_key is not None and key <= prev_key:
            problems.append(f"{label} out of chronological order")
        prev_key = key

        courses = sem.get("courses", [])
        if not courses:
            problems.append(f"{label} empty semester")

        course_cr = 0.0
        for c in courses:
            code = c.get("course_code", "")
            cr = float(c.get("credits_earned") or 0)
            course_cr += cr
            if not code:
                problems.append(f"{label} course with empty code")
            if not (0 < cr <= 15):   # 15 = student teaching (CI 495E)
                problems.append(f"{label} {code}: implausible credits {cr}")
            if not c.get("is_pool"):
                key = _norm_code(code)
                course_counts[key] = course_counts.get(key, 0) + 1
                # A course may repeat only as often as the SAP template itself
                # repeats it (repeatable lessons, split or-pairs); without a
                # template, once is the limit.
                limit = _repeat_limit(key, slot_sets)
                if course_counts[key] == limit + 1:
                    problems.append(f"{label} {code} scheduled more than "
                                    f"{limit}x (template allows {limit})")

        sem_cr = float(sem.get("credits") or 0)
        if abs(sem_cr - course_cr) > 0.11:
            problems.append(f"{label} credits field {sem_cr} != course sum {round(course_cr, 1)}")
        total_credits += course_cr

        is_summer = term.startswith("SU")
        if is_summer:
            if course_cr <= 0:
                problems.append(f"{label} empty summer term")
        elif not (_MIN_SEM_CREDITS <= course_cr <= band_max):
            problems.append(f"{label} {round(course_cr, 1)} credits outside "
                            f"{_MIN_SEM_CREDITS}-{band_max} band")

    # Path-aware total-credit floor: templated majors reproduce a published
    # ~120-credit plan; Layer 1 pads listed bachelor's degrees to ~120; other
    # degrees only get whatever the catalog lists.
    from db import requirements_table
    from boto3.dynamodb.conditions import Key

    floor = 30.0
    if template:
        floor = 100.0
    else:
        resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(major), Limit=1,
        )
        rows = resp.get("Items", [])
        if rows and rows[0].get("degree") in ("B.S.", "B.A.", "B.A.S.", "B.Mus.", "B.F.A."):
            floor = 105.0
    if total_credits < floor:
        problems.append(f"plan totals only {round(total_credits, 1)} credits "
                        f"(floor {floor} for this major's path)")

    return problems


def test_random_majors_timeline():
    if not _dynamo_reachable():
        msg = "DynamoDB Local not reachable — start docker-compose and seed first"
        if pytest:
            pytest.skip(msg)
        print(f"SKIP: {msg}")
        return

    from db import users_table
    from plan_templates import load_template
    from routers.programs import _load_all_programs
    from routers.timeline import get_timeline

    all_programs = _load_all_programs()
    bachelors = [p for p in all_programs if re.search(r",\s*B\.", p)]
    if not bachelors:
        msg = "catalog empty — run setup_tables/load_catalog/rebuild_gen_ed first"
        if pytest:
            pytest.skip(msg)
        print(f"SKIP: {msg}")
        return

    seed = int(os.getenv("TEST_SEED") or random.randrange(1_000_000))
    rng = random.Random(seed)
    picks = rng.sample(bachelors, k=min(N_MAJORS, len(bachelors)))
    print(f"\nTEST_SEED={seed}  (re-run with this env var to reproduce)")

    failures: list[str] = []
    for major in picks:
        user_id = f"pytest-timeline-{uuid.uuid4().hex[:12]}"
        users_table.put_item(Item={"user_id": user_id, "major": major})
        try:
            tl = get_timeline(user_id=user_id)
        except Exception as e:
            failures.append(f"{major}: timeline raised {type(e).__name__}: {e}")
            continue
        finally:
            users_table.delete_item(Key={"user_id": user_id})

        problems = _check_timeline(major, tl, load_template(major, None))
        n_sems = len(tl.get("semesters", []))
        total = round(sum(float(s.get("credits") or 0) for s in tl.get("semesters", [])), 1)
        if problems:
            failures.append(f"{major}:\n    " + "\n    ".join(problems))
            print(f"  FAIL  {major} ({n_sems} semesters, {total} cr)")
        else:
            print(f"  OK    {major} ({n_sems} semesters, {total} cr)")

    assert not failures, (
        f"{len(failures)}/{len(picks)} majors produced a broken timeline "
        f"(TEST_SEED={seed}):\n" + "\n".join(failures)
    )


if __name__ == "__main__":
    test_random_majors_timeline()
    print("PASS")
