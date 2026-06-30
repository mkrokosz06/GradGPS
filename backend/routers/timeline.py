"""
GET /timeline
Returns the student's academic timeline: past semesters from transcript,
current in-progress semester, and future recommended semesters built from
the remaining degree requirements.
"""

import math
import re
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends
from boto3.dynamodb.conditions import Key

from db import requirements_table, users_table, transcript_table
from audit_engine import run_audit, run_gen_ed_audit
from routers.audit import _filter_rows
from deps import get_user_id

router = APIRouter()

# Season sort order within a year
_SEASON_ORDER = {"SP": 0, "SU": 1, "FA": 2}
_SEASON_LABELS = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}


def _term_key(term: str) -> tuple[int, int]:
    """'FA 2025' → (2025, 2) for chronological sorting."""
    parts = term.split()
    if len(parts) != 2:
        return (9999, 99)
    season, year = parts[0], parts[1]
    return (int(year), _SEASON_ORDER.get(season, 99))


def _term_label(term: str) -> str:
    """'FA 2025' → 'Fall 2025'"""
    parts = term.split()
    if len(parts) != 2:
        return term
    return f"{_SEASON_LABELS.get(parts[0], parts[0])} {parts[1]}"


def _next_term(term: str) -> str:
    """Advance to next Fall or Spring (skip Summer — not recommended for major reqs)."""
    parts = term.split()
    if len(parts) != 2:
        return "FA 2027"
    season, year = parts[0], int(parts[1])
    if season in ("SP", "SU"):
        return f"FA {year}"
    return f"SP {year + 1}"


def _collect_missing(audit_result: dict) -> list[dict]:
    """
    Flatten every missing course item out of the audit result.
    Handles normal groups, mixed sub_groups, and choose_credits pools.
    For pairs, only the first option in each pair is emitted (avoids duplicates).
    For choose_credits pools, emits a synthetic summary entry instead of all options.
    """
    missing: list[dict] = []
    seen_pairs: set[str] = set()
    seen_codes: set[str] = set()   # prevent same course appearing in multiple groups

    for group in audit_result.get("groups", []):
        sub_groups = group.get("sub_groups")
        sources = sub_groups if sub_groups else [group]

        for src in sources:
            gtype = src.get("sub_type") or src.get("group_type", "")
            items = src.get("items", [])

            if gtype == "choose_credits":
                # If the pool is already satisfied, skip entirely.
                if not src.get("satisfied"):
                    pool_items = src.get("items", [])
                    ip_credits = sum(
                        float(it.get("credits") or 3)
                        for it in pool_items
                        if it.get("status") == "in_progress"
                    )
                    earned_so_far = (src.get("credits_earned") or 0) + ip_credits
                    needed = max(0, (src.get("threshold") or 0) - earned_so_far)
                    if needed > 0:
                        entry: dict = {
                            "course_code":        group.get("name", "Required Courses"),
                            "course_title":       f"Choose {int(needed)} more credits",
                            "credits":            needed,
                            "is_pool":            True,
                            "pool_needed_credits": int(needed),
                        }
                        # For small pools (≤15 options) include the individual courses
                        # so the mobile UI can render an expandable dropdown.
                        if len(pool_items) <= 15:
                            entry["pool_courses"] = [
                                {
                                    "course_code":  it.get("course_code", ""),
                                    "course_title": it.get("course_title", ""),
                                    "credits":      float(it.get("credits") or 3),
                                }
                                for it in pool_items
                                if it.get("status") == "missing"
                            ]
                        missing.append(entry)
            elif gtype == "choose_courses":
                # Satisfied choose_courses pools are skipped entirely (like choose_credits).
                # Unsatisfied: emit one summary slot for the remaining courses needed.
                if not src.get("satisfied"):
                    pool_items = src.get("items", [])
                    courses_needed = (src.get("threshold") or 0) - (src.get("done") or 0)
                    if courses_needed > 0:
                        entry = {
                            "course_code":         group.get("name", "Required Courses"),
                            "course_title":        f"Choose {int(courses_needed)} more course(s)",
                            "credits":             3,
                            "is_pool":             True,
                            "pool_needed_courses": int(courses_needed),
                        }
                        if len(pool_items) <= 15:
                            entry["pool_courses"] = [
                                {
                                    "course_code":  it.get("course_code", ""),
                                    "course_title": it.get("course_title", ""),
                                    "credits":      float(it.get("credits") or 3),
                                }
                                for it in pool_items
                                if it.get("status") == "missing"
                            ]
                        missing.append(entry)
            else:
                for item in items:
                    if item.get("status") != "missing":
                        continue
                    pid = item.get("pair_group_id")
                    if pid:
                        if pid in seen_pairs:
                            continue
                        seen_pairs.add(pid)
                        # Skip satisfied pairs (pair_status reflects whether any
                        # course in the pair has been completed or is in-progress)
                        if item.get("pair_status") in ("done", "in_progress"):
                            continue
                        # Find the other option to label it
                        partner = next(
                            (it for it in items
                             if it.get("pair_group_id") == pid and it["course_code"] != item["course_code"]),
                            None,
                        )
                        label = (
                            f"{item['course_code']} or {partner['course_code']}"
                            if partner else item["course_code"]
                        )
                        if label in seen_codes:
                            continue
                        seen_codes.add(label)
                        # Add individual codes too so neither appears again
                        # unpaired if they show up in a later group
                        seen_codes.add(item["course_code"])
                        if partner:
                            seen_codes.add(partner["course_code"])
                        missing.append({
                            "course_code": label,
                            "course_title": item.get("course_title", ""),
                            "credits": item.get("credits") or 3,
                        })
                    else:
                        code = item.get("course_code", "")
                        if code in seen_codes:
                            continue
                        seen_codes.add(code)
                        missing.append({
                            "course_code": code,
                            "course_title": item.get("course_title", ""),
                            "credits": item.get("credits") or 3,
                        })

    return missing


def _sort_and_spread(courses: list[dict]) -> list[dict]:
    """
    Order missing courses so that:
      1. Lower course numbers come before higher ones
         (100-level before 200 before 300 before 400).
      2. Within each level tier, courses are round-robined by subject prefix
         (CHEM, MATH, FRNSC, …) so the same department isn't stacked 3+ deep
         in a single semester.
      3. Pool entries (is_pool=True) are left at the very end in original order,
         since they are elective/gen-ed placeholders without a level.
    """
    pools    = [c for c in courses if c.get("is_pool")]
    regulars = [c for c in courses if not c.get("is_pool")]

    def _level(code: str) -> int:
        """Return the hundred-rounded course level: 'CHEM 202' → 200."""
        m = re.search(r"(\d+)", code or "")
        return (int(m.group(1)) // 100) * 100 if m else 0

    def _subject(code: str) -> str:
        """Return the subject prefix: 'CHEM 202' → 'CHEM'."""
        m = re.match(r"^([A-Z]+)", (code or "").strip())
        return m.group(1) if m else ""

    # Group by level tier
    tier_map: dict[int, list] = defaultdict(list)
    for c in regulars:
        tier_map[_level(c.get("course_code", ""))].append(c)

    result: list[dict] = []
    for tier in sorted(tier_map):
        # Within each tier, round-robin by subject so no department clusters
        subj_map: dict[str, list] = defaultdict(list)
        for c in tier_map[tier]:
            subj_map[_subject(c.get("course_code", ""))].append(c)
        buckets = list(subj_map.values())
        while any(buckets):
            for bucket in buckets:
                if bucket:
                    result.append(bucket.pop(0))

    result.extend(pools)
    return result


@router.get("")
def get_timeline(user_id: str = Depends(get_user_id)):
    # ── 1. User ──────────────────────────────────────────────────────────────
    user_resp = users_table.get_item(Key={"user_id": user_id})
    user = user_resp.get("Item")
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    major   = user.get("major")
    subplan = user.get("subplan")
    if not major:
        raise HTTPException(status_code=400, detail="No major selected.")

    # ── 2. Transcript ────────────────────────────────────────────────────────
    tx_resp = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(user_id)
    )
    transcript_courses = tx_resp.get("Items", [])

    # ── 3. Group by term ─────────────────────────────────────────────────────
    # Transfer credits get their own sentinel semester at the front of the timeline.
    transfer_courses = [c for c in transcript_courses if c.get("status") == "transfer"]
    regular_courses  = [c for c in transcript_courses if c.get("status") != "transfer"]

    term_map: dict[str, list] = {}
    for c in regular_courses:
        t = c.get("term") or "Unknown"
        term_map.setdefault(t, []).append(c)

    sorted_terms = sorted(term_map.keys(), key=_term_key)

    # Current term = latest term containing any in_progress course
    current_term = None
    for t in reversed(sorted_terms):
        if any(c.get("status") == "in_progress" for c in term_map[t]):
            current_term = t
            break

    # Build completed / current semester objects
    semesters = []

    # Prepend Transfer semester if any transfer credits exist
    if transfer_courses:
        transfer_credits = round(
            sum(float(c.get("credits_earned", 0)) for c in transfer_courses), 1
        )
        semesters.append({
            "term":    "Transfer",
            "label":   "Transfer Credits",
            "status":  "completed",
            "credits": transfer_credits,
            "courses": [
                {
                    "course_code":    c.get("course_code", ""),
                    "grade":          "TR",
                    "credits_earned": float(c.get("credits_earned", 0)),
                    "status":         "done",
                    "course_title":   c.get("course_title", ""),
                }
                for c in transfer_courses
            ],
        })

    for t in sorted_terms:
        courses = term_map[t]
        status  = "current" if t == current_term else "completed"
        credits = round(
            sum(float(c.get("credits_earned", 0)) for c in courses
                if c.get("status") == "done"),
            1,
        )
        semesters.append({
            "term":    t,
            "label":   _term_label(t),
            "status":  status,
            "credits": credits,
            "courses": [
                {
                    "course_code":    c.get("course_code", ""),
                    "grade":          c.get("grade", ""),
                    "credits_earned": float(c.get("credits_earned", 0)),
                    "status":         c.get("status", "done"),
                }
                for c in courses
            ],
        })

    # ── 4. Audit → future recommendations ───────────────────────────────────
    req_resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(major)
    )
    requirement_rows = req_resp.get("Items", [])
    while "LastEvaluatedKey" in req_resp:
        req_resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(major),
            ExclusiveStartKey=req_resp["LastEvaluatedKey"]
        )
        requirement_rows.extend(req_resp.get("Items", []))

    taken_codes = {c.get("course_code", "").strip().upper() for c in transcript_courses}
    requirement_rows = _filter_rows(requirement_rows, subplan, taken_codes)
    if not requirement_rows:
        raise HTTPException(
            status_code=404,
            detail=f"No requirements found for major: {major}. "
                   "Re-seed the database (setup_tables → load_catalog → seed_gen_ed → seed_matthew).",
        )
    audit_result = run_audit(requirement_rows, transcript_courses)
    missing      = _sort_and_spread(_collect_missing(audit_result))

    # ── 4b. Gen ed audit → one slot per incomplete category ─────────────────
    gen_ed_slots: list[dict] = []
    gen_ed_resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq("__GEN_ED__")
    )
    gen_ed_rows = gen_ed_resp.get("Items", [])
    while "LastEvaluatedKey" in gen_ed_resp:
        gen_ed_resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq("__GEN_ED__"),
            ExclusiveStartKey=gen_ed_resp["LastEvaluatedKey"]
        )
        gen_ed_rows.extend(gen_ed_resp.get("Items", []))

    if gen_ed_rows:
        gen_ed_result = run_gen_ed_audit(gen_ed_rows, transcript_courses)
        for group in gen_ed_result.get("groups", []):
            if not group.get("satisfied"):
                gen_ed_slots.append({
                    "course_code":       group["name"],
                    "course_title":      f"Choose a {group['name']} course",
                    "credits":           3,
                    "is_pool":           True,
                    "gen_ed_categories": [group["name"]],
                })

    # ── 5. Distribute missing courses into future semesters ──────────────────
    # Interleave gen ed slots with major courses so each semester gets a mix
    # (roughly 1-2 gen eds per semester rather than all at the end).
    # Use slot-based scheduling: each item occupies 1+ slots depending on how
    # many courses it represents.  Target COURSES_PER_SEM = 5 slots/semester.
    COURSES_PER_SEM = 5
    base_term = sorted_terms[-1] if sorted_terms else "SP 2026"
    future_term = _next_term(base_term)

    def _item_slots(c: dict) -> int:
        """Scheduling slots this item consumes (pools may span multiple slots)."""
        if c.get("pool_needed_courses"):
            return max(1, int(c["pool_needed_courses"]))
        cr = float(c.get("credits", 3) or 3)
        # Large choose_credits pools (e.g. 18 cr) spread across multiple slots
        return max(1, round(cr / 3))

    def _display_credits(c: dict) -> float:
        """Estimated credits this item represents for the semester credit total."""
        if c.get("pool_needed_courses"):
            return 3.0 * int(c["pool_needed_courses"])
        return float(c.get("credits", 3) or 3)

    # For BS/BA degrees, if the catalogued requirements total less than 120 credits
    # (open electives aren't listed in every catalog), add a free elective placeholder
    # so the schedule reflects the full 4-year length.
    if requirement_rows:
        degree = requirement_rows[0].get("degree", "")
        if degree in ("B.S.", "B.A.", "B.A.S.", "B.Mus.", "B.F.A."):
            total_planned_cr = (
                sum(_display_credits(c) for c in missing)
                + 3.0 * len(gen_ed_slots)
            )
            if total_planned_cr < 120:
                free_cr = int(120 - total_planned_cr)
                missing.append({
                    "course_code":        "Free Electives",
                    "course_title":       f"Choose {free_cr} more elective credits",
                    "credits":            free_cr,
                    "is_pool":            True,
                    "pool_needed_credits": free_cr,
                })

    n_major  = len(missing)
    n_gen_ed = len(gen_ed_slots)

    # Estimate semester count from total slots to size gen-ed cadence
    total_slots = sum(_item_slots(c) for c in missing) + n_gen_ed
    n_sems      = max(1, math.ceil(total_slots / COURSES_PER_SEM))

    # Cap gen ed per semester at 2 so major courses aren't squeezed out
    gen_ed_per_sem = min(2, math.ceil(n_gen_ed / n_sems)) if n_gen_ed else 0

    mi, gi = 0, 0
    chunks: list[list[dict]] = []
    while mi < n_major or gi < n_gen_ed:
        chunk: list[dict] = []
        slots_used = 0
        # How many gen eds are we adding this semester?
        # Dynamically reduce major slots only by the gen eds actually available,
        # so semesters stay full after gen ed is exhausted.
        gen_eds_remaining = n_gen_ed - gi
        gen_eds_this_sem  = min(gen_ed_per_sem, gen_eds_remaining)
        avail_major       = COURSES_PER_SEM - gen_eds_this_sem
        # Fill major courses up to avail_major slots
        while mi < n_major:
            c = missing[mi]
            s = min(_item_slots(c), avail_major)  # single entry can't exceed a semester
            if slots_used > 0 and slots_used + s > avail_major:
                break
            chunk.append(c)
            slots_used += s
            mi += 1
        # Add gen ed slots (capped per semester)
        gen_ed_added = 0
        while gi < n_gen_ed and gen_ed_added < gen_ed_per_sem:
            chunk.append(gen_ed_slots[gi])
            gi += 1
            gen_ed_added += 1
        if chunk:
            chunks.append(chunk)
        else:
            break  # safety valve
    for chunk in chunks:
        est_credits = round(sum(_display_credits(c) for c in chunk), 1)
        semesters.append({
            "term":    future_term,
            "label":   _term_label(future_term),
            "status":  "upcoming",
            "credits": est_credits,
            "courses": [
                {
                    "course_code":         c.get("course_code", ""),
                    "course_title":        c.get("course_title", ""),
                    "credits_earned":      float(c.get("credits", 3) or 3),
                    "status":              "missing",
                    "grade":               "",
                    "is_pool":             c.get("is_pool", False),
                    "gen_ed_categories":   c.get("gen_ed_categories"),
                    "pool_courses":        c.get("pool_courses"),
                    "pool_needed_credits": c.get("pool_needed_credits"),
                    "pool_needed_courses": c.get("pool_needed_courses"),
                }
                for c in chunk
            ],
        })
        future_term = _next_term(future_term)

    # ── 6. Summary ───────────────────────────────────────────────────────────
    transcript_credits = round(
        sum(float(c.get("credits_earned", 0)) for c in transcript_courses
            if c.get("status") in ("done", "transfer")),
        1,
    )

    return {
        "major":               major,
        "subplan":             subplan,
        "transcript_credits":  transcript_credits,
        "semesters":           semesters,
    }
