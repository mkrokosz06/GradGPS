"""
GET /timeline
Returns the student's academic timeline: past semesters from transcript,
current in-progress semester, and future recommended semesters built from
the remaining degree requirements.
"""

import math
import re
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException, Depends
from boto3.dynamodb.conditions import Key

from db import requirements_table, users_table, transcript_table
from audit_engine import run_audit, run_gen_ed_audit
from routers.audit import _filter_rows
from deps import get_user_id
from plan_templates import load_template
from sap_schedule import (build_taken_set, build_gen_ed_satisfied,
                          build_used_codes, build_satisfied_req_codes,
                          build_gen_ed_courses, match_template)
from routers.user_choices import get_user_choices

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


def _preceding_summer(term: str) -> str:
    """Summer term immediately before a given Fall/Spring term.
    'FA 2028' → 'SU 2028'  (summer right before that fall)
    'SP 2028' → 'SU 2027'  (summer of the prior calendar year)
    """
    parts = term.split()
    if len(parts) != 2:
        return "SU 2027"
    season, year = parts[0], int(parts[1])
    if season == "SP":
        return f"SU {year - 1}"
    return f"SU {year}"


def _candidate_codes(course_code: str) -> list[str]:
    """Split a (possibly paired) requirement code into its option codes.
    'ENGL 202C or ENGL 202D' → ['ENGL 202C', 'ENGL 202D']; 'IST 210' → ['IST 210'].
    """
    raw = (course_code or "").strip().upper()
    return [p.strip() for p in raw.split(" OR ") if p.strip()]


def _strip_w(code: str) -> str:
    """Strip a trailing Writing (W) designation so it matches the catalog's
    base code: 'ETI 300W' → 'ETI 300'. Section letters (A/B/C) are preserved."""
    m = re.match(r"^([A-Z]+ \d+)W$", (code or "").strip().upper())
    return m.group(1) if m else (code or "").strip().upper()


def _is_writing_code(code: str) -> bool:
    """A requirement code carrying a Writing Across the Curriculum suffix
    (W/M/X/Y), e.g. 'ETI 300W'. Section letters (A/B/C) don't count."""
    return bool(re.search(r"\d[WXYM]$", (code or "").strip().upper()))


def _is_internship(item: dict) -> bool:
    """A required internship course (title says 'Internship', or PSU's 495 number)."""
    if "INTERNSHIP" in (item.get("course_title") or "").upper():
        return True
    for cc in _candidate_codes(item.get("course_code", "")):
        m = re.search(r"\b(\d{3})\b", cc)
        if m and m.group(1) == "495":
            return True
    return False


def _gen_ed_effectively_satisfied(group: dict, planned: list[dict]) -> bool:
    """Whether a gen-ed category will be satisfied by the time the student
    graduates — counting not just completed courses but also courses currently
    in progress and future major courses already scheduled in the plan.

    The base audit only credits *completed* courses, so a category the student
    is actively taking (e.g. SOC 119 → US) or will cover via a required major
    course (e.g. ENGL 202C → GWS) would otherwise generate a redundant slot.
    """
    if group.get("satisfied"):
        return True

    gtype     = group.get("group_type", "")
    threshold = group.get("threshold") or 0
    items     = group.get("items", [])
    pool_codes = {_strip_w(it.get("course_code", "")) for it in items}
    name_up    = (group.get("name") or "").upper()
    is_gws     = name_up.startswith("GWS") or "WRITING ACROSS" in name_up

    if gtype == "choose_credits":
        have = float(group.get("credits_earned") or 0)
        seen: set[str] = set()
        for it in items:
            code = it.get("course_code", "")
            if it.get("status") == "in_progress" and code not in seen:
                seen.add(code)
                have += float(it.get("credits") or 3)
        for c in planned:
            if any(_strip_w(cc) in pool_codes for cc in _candidate_codes(c.get("course_code", ""))):
                have += float(c.get("credits") or 3)
        return have >= threshold

    if gtype == "choose_courses":
        have = int(group.get("done") or 0)
        seen = set()
        for it in items:
            code = it.get("course_code", "")
            if it.get("status") == "in_progress" and code not in seen:
                seen.add(code)
                have += 1
        for c in planned:
            cands = _candidate_codes(c.get("course_code", ""))
            if any(_strip_w(cc) in pool_codes or (is_gws and cc.endswith("W")) for cc in cands):
                have += 1
        return have >= threshold

    if gtype == "writing_intensive":
        # Writing Across the Curriculum: 3 credits of W-designated coursework.
        thr = threshold or 3
        have = float(group.get("credits_earned") or 0)          # completed W credits
        for it in items:                                         # in-progress W courses
            if it.get("status") == "in_progress":
                have += float(it.get("credits") or 3)
        for c in planned:                                        # planned major W courses
            if any(_is_writing_code(cc) for cc in _candidate_codes(c.get("course_code", ""))):
                have += float(c.get("credits") or 3)
        return have >= thr

    if gtype == "choose_one":
        return any(it.get("status") in ("done", "in_progress") for it in items)

    return bool(group.get("satisfied"))


def _collect_missing(audit_result: dict, course_choices: dict[str, str] | None = None) -> list[dict]:
    """
    Flatten every missing course item out of the audit result.
    Handles normal groups, mixed sub_groups, and choose_credits pools.
    For pairs, only the first option in each pair is emitted (avoids duplicates).
    For choose_credits pools, emits a synthetic summary entry instead of all options.

    Named courses and choose-one pairs carry a stable `slot_key`/`slot_kind` (and,
    for pairs, `options`) so the class selector can pin them or swap the pair's
    chosen course; a stored choice in `course_choices` is applied here.
    """
    course_choices = course_choices or {}
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
                        pair_codes = [item["course_code"]]
                        if partner:
                            pair_codes.append(partner["course_code"])
                        credits = item.get("credits") or 3
                        skey = "one:" + "|".join(sorted({_strip_w(c) for c in pair_codes}))
                        entry = {
                            "course_code": label,
                            "course_title": item.get("course_title", ""),
                            "credits": credits,
                            "slot_key": skey,
                            "slot_kind": "choose_one",
                            "options": [
                                {"course_code": c, "course_title": "", "credits": float(credits or 3)}
                                for c in pair_codes
                            ],
                        }
                        chosen = course_choices.get(skey)
                        if chosen and any(chosen.strip().upper() == c.strip().upper() for c in pair_codes):
                            entry["course_code"] = chosen
                            entry["chosen_code"] = chosen
                        missing.append(entry)
                    else:
                        code = item.get("course_code", "")
                        if code in seen_codes:
                            continue
                        seen_codes.add(code)
                        missing.append({
                            "course_code": code,
                            "course_title": item.get("course_title", ""),
                            "credits": item.get("credits") or 3,
                            "slot_key": f"course:{_strip_w(code)}",
                            "slot_kind": "course",
                        })

    return missing


def _sort_named(courses: list[dict]) -> list[dict]:
    """
    Order named (non-pool) missing courses so that:
      1. Lower course numbers come before higher ones
         (100-level before 200 before 300 before 400) — a rough prerequisite proxy.
      2. Within each level tier, courses are round-robined by subject prefix
         (CHEM, MATH, FRNSC, …) so the same department isn't stacked 3+ deep
         in a single semester.
    Pool/placeholder entries are handled separately by _expand_pool and the packer.
    """
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
    for c in courses:
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

    return result


# ── Pool expansion + credit-band packing (timeline Layer 1) ──────────────────
#
# A degree's remaining requirements include large "pools" — choose_credits /
# choose_courses buckets and the free-elective pad — that carry many credits but
# no single named course.  Historically each pool was emitted as ONE item at its
# full credit weight and appended after every named course, so the scheduler
# either dumped a 30-credit blob into a single semester or left the back half of
# the plan empty.  _expand_pool breaks a pool into ~3-credit placeholder slots so
# the packer can distribute it, and _build_future_semesters packs everything to a
# realistic ~15-credit band with named courses spread across the whole plan.

_TARGET_CREDITS = 15.0   # aim for a ~15-credit semester
_MAX_CREDITS    = 18.0   # never push a semester past this
_GEN_ED_PER_SEM = 2      # at most this many gen-ed placeholders per semester
_MERGE_MIN      = 10.0   # SAP reflow: a semester lighter than this is merged forward


def _display_credits(c: dict) -> float:
    """Credits this item contributes to a semester total.  After _expand_pool
    every item (named course, gen-ed slot, or pool slot) carries a real per-slot
    credit value, so this is just a safe read of `credits`."""
    return float(c.get("credits", 3) or 3)


def _past_display_credits(c: dict) -> float:
    """Credit count to show on a completed/current transcript card: earned for
    graded courses, attempted (`credits`) for in-progress ones (earned still 0)."""
    earned = float(c.get("credits_earned", 0) or 0)
    if earned == 0 and c.get("status") == "in_progress":
        return float(c.get("credits", 0) or 0)
    return earned


_catalog_title_map: dict[str, str] | None = None


def _catalog_titles() -> dict[str, str]:
    """course_code -> official title, from one cached scan of the requirements
    table across all programs. A code appears in many programs, and scraper
    artifacts give a few of them garbage titles (e.g. IST 495 as ', 295A , or
    295B *'), so pick the title the MOST programs agree on — a majority vote is
    robust to those one-off junk titles in a way the old longest-wins heuristic
    wasn't. Ties break toward the longer title. Titles with no letters ('*7')
    and pure-digit titles (ETI junk rows) are dropped before voting."""
    global _catalog_title_map
    if _catalog_title_map is not None:
        return _catalog_title_map
    counts: dict[str, Counter] = defaultdict(Counter)
    scan_kwargs: dict = {"ProjectionExpression": "course_code, course_title"}
    while True:
        resp = requirements_table.scan(**scan_kwargs)
        for it in resp.get("Items", []):
            code = (it.get("course_code") or "").strip().upper()
            title = (it.get("course_title") or "").strip()
            if not code or not title or title.isdigit():
                continue
            if not any(ch.isalpha() for ch in title):   # e.g. '*7'
                continue
            counts[code][title] += 1
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        scan_kwargs["ExclusiveStartKey"] = last
    m: dict[str, str] = {}
    for code, ctr in counts.items():
        # Most-agreed title wins; on a tie, prefer the longer one.
        m[code] = max(ctr.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
    _catalog_title_map = m
    return m


_REAL_CODE_RE = re.compile(r"^[A-Z]{2,6}\s+\d")


def _fill_future_titles(semesters: list[dict]) -> None:
    """Backfill empty course_title on real (non-pool) recommended cards from the
    catalog, so 'Plan your registration' shows names, not just codes."""
    titles: dict[str, str] | None = None
    for sem in semesters:
        for c in sem.get("courses", []):
            if c.get("course_title") or c.get("is_pool"):
                continue
            code = (c.get("course_code") or "").strip().upper()
            if " OR " in code or not _REAL_CODE_RE.match(code):
                continue
            if titles is None:
                titles = _catalog_titles()
            norm = re.sub(r"[WHNMXY]$", "", code).strip()
            t = titles.get(code) or titles.get(norm)
            if t:
                c["course_title"] = t


def _expand_pool(entry: dict) -> list[dict]:
    """Split a pool entry into ~3-credit placeholder slots the packer can spread
    across semesters.  Non-pool entries pass through unchanged (single-item list).

    Each emitted slot keeps the pool's identity and dropdown (`pool_courses`,
    `gen_ed_categories`) so the mobile UI renders it exactly as before, but
    carries only its own slice of the credits — so a 31-credit Free-Electives
    pool becomes eleven schedulable slots instead of one 31-credit blob.
    """
    if not entry.get("is_pool"):
        return [entry]

    # choose_courses pools count courses, not credits → one ~3cr slot per course.
    if entry.get("pool_needed_courses"):
        n = max(1, int(entry["pool_needed_courses"]))
        sizes = [3.0] * n
    else:
        # Credit-based pool (choose_credits / free electives) → split into
        # 3-credit slots with a smaller final remainder.
        if entry.get("pool_needed_credits") is not None:
            total = float(entry["pool_needed_credits"])
        else:
            total = float(entry.get("credits") or 3)
        if total <= 0:
            return []
        sizes = []
        remaining = total
        while remaining > 1e-6:
            take = 3.0 if remaining >= 3.0 - 1e-9 else round(remaining, 2)
            sizes.append(take)
            remaining -= take

    slots: list[dict] = []
    for cr in sizes:
        slot = dict(entry)
        slot["credits"] = cr
        crd = int(cr) if float(cr).is_integer() else cr
        if entry.get("pool_needed_courses"):
            slot["pool_needed_courses"] = 1
        if entry.get("pool_needed_credits") is not None:
            slot["pool_needed_credits"] = crd
        # Re-label per slot so a split pool doesn't repeat the whole-pool credit
        # count on every card (e.g. eleven cards each reading "Choose 31 credits").
        if "elective" in (entry.get("course_title") or "").lower():
            slot["course_title"] = f"Choose {crd} more elective credits"
        elif entry.get("pool_needed_courses"):
            slot["course_title"] = "Choose 1 more course"
        else:
            slot["course_title"] = f"Choose {crd} more credits"
        slots.append(slot)
    return slots


def _slice_even(items: list, n: int) -> list[list]:
    """Split a list into n contiguous groups, as evenly as possible, preserving
    order.  18 items over 8 groups → sizes 2,2,2,3,2,2,2,3."""
    if n <= 0:
        return []
    L = len(items)
    return [items[(i * L) // n:((i + 1) * L) // n] for i in range(n)]


def _emit_semester(term: str, courses: list[dict]) -> dict:
    """Build an upcoming-semester object in the mobile-facing schema."""
    return {
        "term":    term,
        "label":   _term_label(term),
        "status":  "upcoming",
        "credits": round(sum(_display_credits(c) for c in courses), 1),
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
                "pool_ref":            c.get("pool_ref"),
                # Class selector metadata (present on actionable future slots).
                "slot_key":            c.get("slot_key"),
                "slot_kind":           c.get("slot_kind"),
                "options":             c.get("options"),
                "chosen_code":         c.get("chosen_code"),
                "pinned":              c.get("pinned", False),
                "searchable":          c.get("searchable", False),
            }
            for c in courses
        ],
    }


def _build_future_semesters(
    named: list[dict],
    gen_ed_slots: list[dict],
    pool_slots: list[dict],
    base_term: str,
    internship_items: list[dict] | None = None,
) -> list[dict]:
    """Pack the remaining requirements into ~15-credit future semesters.

    Named courses (the prereq-ordered spine) are spread evenly across the whole
    plan so no semester is pure filler; gen-ed placeholders are capped per
    semester; pool/elective slots top each semester up to the credit band.  A
    required internship is lifted into its own summer term between junior and
    senior year.
    """
    internship_items = internship_items or []
    future_term = _next_term(base_term)

    total_cr = sum(_display_credits(c) for c in (*named, *gen_ed_slots, *pool_slots))
    n_sems = max(1, math.ceil(total_cr / _TARGET_CREDITS)) if total_cr else 0
    named_alloc = _slice_even(named, n_sems)

    # Even out the load: aim for total/n_sems credits per semester rather than a
    # hard 15, so the final semester isn't left holding a small remainder.
    target = min(_TARGET_CREDITS, total_cr / n_sems) if n_sems else _TARGET_CREDITS

    gi = pi = 0

    def _fill(chunk: list[dict], cr: float) -> float:
        """Add gen-ed (capped) then pool slots to a chunk up to the credit band."""
        nonlocal gi, pi
        added_ge = 0
        while gi < len(gen_ed_slots) and added_ge < _GEN_ED_PER_SEM and cr < target:
            ic = _display_credits(gen_ed_slots[gi])
            if chunk and cr + ic > _MAX_CREDITS:
                break
            chunk.append(gen_ed_slots[gi]); cr += ic; gi += 1; added_ge += 1
        while pi < len(pool_slots) and cr < target:
            ic = _display_credits(pool_slots[pi])
            if chunk and cr + ic > _MAX_CREDITS:
                break
            chunk.append(pool_slots[pi]); cr += ic; pi += 1
        return cr

    chunks: list[list[dict]] = []
    for s in range(n_sems):
        chunk = list(named_alloc[s])
        _fill(chunk, sum(_display_credits(c) for c in chunk))
        chunks.append(chunk)

    # Any gen-ed / pool slots that didn't fit the credit-sized plan → extra
    # semesters (still balanced, still gen-ed capped).
    while gi < len(gen_ed_slots) or pi < len(pool_slots):
        chunk: list[dict] = []
        _fill(chunk, 0.0)
        if not chunk:  # safety valve — force progress on an oversized straggler
            if gi < len(gen_ed_slots):
                chunk.append(gen_ed_slots[gi]); gi += 1
            elif pi < len(pool_slots):
                chunk.append(pool_slots[pi]); pi += 1
        chunks.append(chunk)

    chunks = [c for c in chunks if c]

    # Place a required internship in its own summer term between junior and
    # senior year: right before the final two academic semesters.
    semesters: list[dict] = []
    internship_at = (len(chunks) - 2) if internship_items else -1
    placed = False
    for idx, chunk in enumerate(chunks):
        if internship_items and not placed and idx >= max(0, internship_at):
            semesters.append(_emit_semester(_preceding_summer(future_term), internship_items))
            placed = True
        semesters.append(_emit_semester(future_term, chunk))
        future_term = _next_term(future_term)
    if internship_items and not placed:
        semesters.append(_emit_semester(_preceding_summer(future_term), internship_items))

    return semesters


def _reflow_reproduce(records: list[dict], base_term: str) -> list[dict]:
    """Reproduce the published plan for an on-track / no-transcript student.

    Unsatisfied slots keep the template's ordering, per-semester groupings, AND
    each semester's own season — the published plan is already prerequisite-
    sequenced, credit-balanced, and correctly places summer terms (internships,
    field camps).  Any light Fall/Spring fragments a partially-complete student
    leaves behind merge forward; summer terms never merge.  With nothing dropped
    this reproduces the official plan exactly, summers included.
    """
    def _cr(items):
        return sum(_display_credits(it) for it in items)

    # Group unsatisfied items by their template semester, preserving order and
    # carrying the template semester's season.
    groups: list[list] = []   # each: [season, [items]]
    cur_idx: object = object()   # sentinel so the first slot always opens a group
    for r in records:
        if r["satisfied"]:
            continue
        if r["sem_index"] != cur_idx:
            groups.append([r.get("season") or "FA", []])
            cur_idx = r["sem_index"]
        groups[-1][1].append(r["item"])
    groups = [g for g in groups if g[1]]

    merged: list[list] = []
    for season, items in groups:
        prev = merged[-1] if merged else None
        if (prev and prev[0] != "SU" and season != "SU"
                and (_cr(prev[1]) < _MERGE_MIN or _cr(items) < _MERGE_MIN)
                and _cr(prev[1]) + _cr(items) <= _MAX_CREDITS):
            prev[1].extend(items)
        else:
            merged.append([season, list(items)])
    groups = merged

    # Assign real calendar terms, following each semester's own season so a
    # summer term lands in summer (not collapsed into the next Fall).
    semesters: list[dict] = []
    cursor = base_term
    for season, items in groups:
        if season == "SU":
            cursor = _preceding_summer(_next_term(cursor))   # the summer after `cursor`
        else:
            cursor = _next_term(cursor)                      # next Fall/Spring
        semesters.append(_emit_semester(cursor, items))

    return semesters


def _reflow_rebalance(records: list[dict], base_term: str) -> list[dict]:
    """Reflow for a partially-complete student, re-packing the REMAINING slots.

    A behind/scattered student who has finished many early template slots would,
    under the reproduce path, be left with the template's lumpy per-semester
    groupings (a light semester here, a heavy one there) — stretching graduation
    past where the real remaining load warrants.  Instead we re-pack the remaining
    (prerequisite-ordered) slots into balanced ~15-credit semesters and lift a
    required internship into its own summer term between junior and senior year —
    the same shape the Layer 1 packer produces.
    """
    unsatisfied = [r["item"] for r in records if not r["satisfied"]]
    internship  = [it for it in unsatisfied if _is_internship(it)]
    academic    = [it for it in unsatisfied if not _is_internship(it)]

    # Pack academic slots, in order, into as FEW semesters as the credit band
    # allows, split evenly.  Using the fewest semesters (each up to the 18-credit
    # max) keeps a behind student from stretching an extra term just to carry a
    # few trailing padding credits — those fold into the senior semesters — while
    # the even split avoids two maxed-out semesters next to a light one.
    total_cr = sum(_display_credits(it) for it in academic)
    n_sems = max(1, math.ceil(total_cr / _MAX_CREDITS)) if total_cr else 0
    chunks = [c for c in _slice_even(academic, n_sems) if c]

    # Lay chunks onto alternating Fall/Spring terms.
    acad: list[tuple[str, list[dict]]] = []
    future_term = _next_term(base_term)
    for chunk in chunks:
        acad.append((future_term, chunk))
        future_term = _next_term(future_term)

    if not internship:
        return [_emit_semester(t, c) for t, c in acad]

    # Drop the internship into its own summer that opens senior year: the summer
    # before the Fall among the final two academic terms.  A summer only validly
    # precedes a Fall (there is no summer between a Fall and the next Spring), so
    # anchoring on that Fall places the internship between junior spring and
    # senior fall regardless of the plan's term parity.
    tail = acad[-2:] if len(acad) >= 2 else acad
    anchor_fall = next((t for t, _ in tail if t.startswith("FA")), acad[-1][0])
    su_term = _preceding_summer(anchor_fall)

    semesters: list[dict] = []
    for t, c in acad:
        if t == anchor_fall:
            semesters.append(_emit_semester(su_term, internship))
        semesters.append(_emit_semester(t, c))
    return semesters


def _reflow_template(records: list[dict], base_term: str) -> list[dict]:
    """Reflow matched SAP-template slots into future semesters.

    A no-transcript / on-track student (nothing satisfied) reproduces the
    published plan exactly (`_reflow_reproduce`).  A partially-complete student
    — who has already satisfied some slots — gets the remaining, prerequisite-
    ordered work re-packed into balanced semesters with the internship placed
    between junior and senior year (`_reflow_rebalance`), so graduation reflects
    the real remaining load rather than the template's now-lopsided groupings.
    """
    if any(r["satisfied"] for r in records):
        return _reflow_rebalance(records, base_term)
    return _reflow_reproduce(records, base_term)


def _build_layer1_future(
    audit_result: dict,
    gen_ed_result: dict,
    requirement_rows: list[dict],
    transcript_courses: list[dict],
    transfer_courses: list[dict],
    base_term: str,
    course_choices: dict[str, str] | None = None,
) -> list[dict]:
    """Layer 1 fallback: build future semesters from the audit alone (no SAP
    template) with the credit-band packer.  Used for every major that doesn't
    have a plan template."""
    collected     = _collect_missing(audit_result, course_choices)
    named_courses = _sort_named([c for c in collected if not c.get("is_pool")])
    raw_pools     = [c for c in collected if c.get("is_pool")]

    # Gen ed → one slot per still-incomplete category.
    course_choices = course_choices or {}
    gen_ed_slots: list[dict] = []
    for group in gen_ed_result.get("groups", []):
        # Suppress a category if it will be covered by courses already in
        # progress or by future major courses in the plan.
        if not _gen_ed_effectively_satisfied(group, named_courses):
            writing = group.get("group_type") == "writing_intensive"
            title = ("Choose a writing-intensive (W) course" if writing
                     else f"Choose a {group['name']} course")
            # Stable slot identity so the class-selector picker can search for a
            # course to fill this category (and persist/pin the choice).
            token = (group["name"].split(":")[0].strip().upper().split(" ")[0]
                     if group.get("name") else "")
            slot: dict = {
                "course_code":       group["name"],
                "course_title":      title,
                "credits":           3,
                "is_pool":           True,
                "gen_ed_categories": [group["name"]],
                "slot_key":          f"gened:{token}",
                "slot_kind":         "gen_ed",
                # WAC is a designation, not a course list — not searchable.
                "searchable":        not writing,
            }
            chosen = course_choices.get(slot["slot_key"])
            if chosen and not writing:
                # A picked course now fills this category slot (display/schedule only;
                # the gen-ed audit stays the source of truth for completion).
                slot["course_code"] = chosen
                slot["chosen_code"] = chosen
                # Drop the "Choose a … course" placeholder so _fill_future_titles
                # backfills the chosen course's real catalog title on the card.
                slot["course_title"] = ""
                slot["is_pool"] = False
            gen_ed_slots.append(slot)

    # Expand every requirement pool (choose_credits / choose_courses) into
    # ~3-credit placeholder slots so the packer can spread it across semesters
    # instead of dumping it whole into one.
    pool_slots: list[dict] = []
    for p in raw_pools:
        pool_slots.extend(_expand_pool(p))

    # For BS/BA degrees, if the catalogued requirements total less than 120 credits
    # (open electives aren't listed in every catalog), add free-elective placeholder
    # slots so the schedule reflects the full 4-year length.
    if requirement_rows:
        degree = requirement_rows[0].get("degree", "")
        if degree in ("B.S.", "B.A.", "B.A.S.", "B.Mus.", "B.F.A."):
            # Credits the student has already banked or is currently earning
            # (completed + in-progress + transfer). These all count toward the
            # 120-credit degree total, so they must be included or the
            # free-elective padding double-counts them.
            earned_cr = sum(
                # done courses report earned credits; in-progress ones aren't
                # graded yet (earned = 0) and attempted credits aren't stored,
                # so estimate the standard 3 credits per in-progress course.
                float(c.get("credits_earned", 0)) if c.get("status") == "done"
                else 3.0
                for c in transcript_courses
                if c.get("status") in ("done", "in_progress")
            ) + sum(float(c.get("credits_earned", 0)) for c in transfer_courses)
            total_planned_cr = (
                earned_cr
                + sum(_display_credits(c) for c in named_courses)
                + sum(_display_credits(c) for c in pool_slots)
                + 3.0 * len(gen_ed_slots)
            )
            # Only pad if the gap is a meaningful course-sized chunk (≥3 cr);
            # smaller remainders are just estimation noise (in-progress credits
            # are approximated), not a real elective to schedule.
            if total_planned_cr <= 117:
                free_cr = int(120 - total_planned_cr)
                pool_slots.extend(_expand_pool({
                    "course_code":         "Free Electives",
                    "course_title":        f"Choose {free_cr} more elective credits",
                    "credits":             free_cr,
                    "is_pool":             True,
                    "pool_needed_credits": free_cr,
                }))

    # Pull a required internship out of the normal course flow — it becomes its
    # own dedicated summer term between junior and senior year (inserted inside
    # _build_future_semesters).  Extracted after the free-elective math above so
    # its credits still count toward the 120-credit total.
    internship_items = [c for c in named_courses if _is_internship(c)]
    if internship_items:
        named_courses = [c for c in named_courses if not _is_internship(c)]

    return _build_future_semesters(
        named_courses, gen_ed_slots, pool_slots, base_term, internship_items,
    )


def _semester_credits(courses: list[dict]) -> float:
    return round(sum(float(c.get("credits_earned", 3) or 3) for c in courses), 1)


def _apply_pins(future: list[dict], pins: dict[str, str]) -> list[dict]:
    """Anchor pinned courses to their pinned terms, then re-pack around them.

    `future` is the emitted upcoming-semester list; `pins` maps slot_key → term.
    Only emitted courses carrying that slot_key are moved (a pin for a course the
    student has since completed simply matches nothing and is inert).  Conflict
    rules: a pin whose term has fallen into the past moves to the earliest future
    term (`pin_moved`); a term pushed past the credit cap bumps its lowest-priority
    *unpinned* course forward.  Placement is best-effort — the audit stays the
    source of truth for what's required.
    """
    if not pins or not future:
        return future

    earliest = min((s["term"] for s in future), key=_term_key)
    by_term: dict[str, dict] = {s["term"]: s for s in future}

    def _ensure_term(term: str) -> dict:
        if term not in by_term:
            by_term[term] = {
                "term": term, "label": _term_label(term),
                "status": "upcoming", "credits": 0.0, "courses": [],
            }
        return by_term[term]

    # 1. Detach every pinned course from where the packer put it.
    moved: list[tuple[dict, str]] = []
    for sem in future:
        keep = []
        for c in sem["courses"]:
            sk = c.get("slot_key")
            if sk and sk in pins:
                target = pins[sk]
                if _term_key(target) < _term_key(earliest):
                    target = earliest
                    c["pin_moved"] = True
                c["pinned"] = True
                moved.append((c, target))
            else:
                keep.append(c)
        sem["courses"] = keep

    # 2. Re-attach each pinned course to its target term (creating it if needed).
    for c, target in moved:
        _ensure_term(target)["courses"].append(c)

    # 3. Relieve any over-cap term by bumping its lowest-priority unpinned course
    #    forward (pools/gen-ed placeholders first, then the last-listed course).
    for _ in range(len(by_term) * 4):  # bounded: cascades can't loop forever
        ordered = sorted(by_term.values(), key=lambda s: _term_key(s["term"]))
        changed = False
        for sem in ordered:
            if _semester_credits(sem["courses"]) <= _MAX_CREDITS:
                continue
            idx = next((i for i, c in enumerate(sem["courses"])
                        if not c.get("pinned") and c.get("is_pool")), None)
            if idx is None:
                idx = next((i for i in range(len(sem["courses"]) - 1, -1, -1)
                            if not sem["courses"][i].get("pinned")), None)
            if idx is None:
                continue  # everything here is pinned — allow the overflow
            bumped = sem["courses"].pop(idx)
            _ensure_term(_next_term(sem["term"]))["courses"].append(bumped)
            changed = True
            break
        if not changed:
            break

    # 4. Recompute totals, drop empties, return in chronological order.
    result = []
    for sem in sorted(by_term.values(), key=lambda s: _term_key(s["term"])):
        if not sem["courses"]:
            continue
        sem["credits"] = _semester_credits(sem["courses"])
        result.append(sem)
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
                    "credits_earned": _past_display_credits(c),
                    "course_title":   c.get("course_title", ""),
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

    # A published-plan template renders the timeline on its own (it uses the
    # transcript + gen-ed audit, not the major's requirement rows), so a major
    # with a template but thin/empty catalog requirements must NOT 404 — only a
    # major with neither is a real dead end.
    template = load_template(major, subplan)
    if not requirement_rows and not template:
        raise HTTPException(
            status_code=404,
            detail=f"No requirements found for major: {major}. "
                   "Re-seed the database (setup_tables → load_catalog → seed_gen_ed → seed_matthew).",
        )
    audit_result = run_audit(requirement_rows, transcript_courses)

    # ── 4b. Gen ed audit (used by both the SAP-template and Layer 1 paths) ──
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
    gen_ed_result = (
        run_gen_ed_audit(gen_ed_rows, transcript_courses) if gen_ed_rows else {"groups": []}
    )

    # ── 5. Build future semesters ────────────────────────────────────────────
    base_term = sorted_terms[-1] if sorted_terms else "SP 2026"

    # SAP hybrid: if this major has a published-plan template, follow it (ordered,
    # prerequisite-sequenced, complete to 120 cr) and reflow the student's real
    # state onto it.  Every major WITHOUT a template falls back to the Layer 1
    # credit-band packer, exactly as before — so only templated majors change.
    # (`template` was loaded above, before the requirement-rows 404 check.)
    # Class-selector decisions: which course fills an option-bearing slot
    # (course_choices) and which term a slot is pinned to (pins). Both key on the
    # stable slot_key the timeline emits; applied below and in _apply_pins.
    choices        = get_user_choices(user_id)
    course_choices = {k: v["chosen_course"] for k, v in choices.items() if v.get("chosen_course")}
    pins           = {k: v["pinned_term"]   for k, v in choices.items() if v.get("pinned_term")}

    if template:
        # The major audit is the source of truth for course equivalences/pairs
        # (MATH 110/140, STAT 200/SCM 200): fold its satisfied requirement codes
        # into the taken set so the template stops re-scheduling met requirements.
        taken = (build_taken_set(transcript_courses)
                 | build_satisfied_req_codes(audit_result))
        records = match_template(
            template,
            taken,
            build_gen_ed_satisfied(gen_ed_result),
            transcript_courses=transcript_courses,
            used_codes=build_used_codes(audit_result, gen_ed_result),
            gen_ed_courses=build_gen_ed_courses(gen_ed_result),
            course_choices=course_choices,
        )
        future = _reflow_template(records, base_term)
    else:
        future = _build_layer1_future(
            audit_result, gen_ed_result, requirement_rows,
            transcript_courses, transfer_courses, base_term,
            course_choices=course_choices,
        )

    semesters.extend(_apply_pins(future, pins))

    # Recommended courses often come from major rows with no title — fill from the
    # cross-program catalog so Home/Timeline show names next to the codes.
    _fill_future_titles(semesters)

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
