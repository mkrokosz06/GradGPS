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
from honors import apply_thesis_rule
from sap_schedule import (build_taken_set, build_gen_ed_satisfied,
                          build_used_codes, build_satisfied_req_codes, build_major_pool_codes,
                          build_gen_ed_courses, build_gen_ed_open, match_template)
from routers.user_choices import get_user_choices
from routers.courses import _bulletin_courses
from substitutions import get_substitutions
import credential_choices
from credentials_audit import audit_declared_credentials
import entrance_to_major
import course_prereqs

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
                            _make_pool_selectable(entry, src.get("pool_seq"))
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
                            _make_pool_selectable(entry, src.get("pool_seq"))
                        missing.append(entry)
            elif gtype in ("dept_credits", "unstructured_credits"):
                # Credential pools (minors/certificates). Both are rules rather than
                # course lists, so there is nothing to enumerate into `pool_courses` —
                # the slot carries the bulletin's own wording instead.
                if not src.get("satisfied"):
                    needed = src.get("credits_needed")
                    if needed is None:
                        needed = src.get("threshold") or 3
                    if needed > 0:
                        wording = src.get("pool_text") or group.get("name", "")
                        entry = {
                            "course_code":         group.get("name", "Requirements"),
                            "course_title":        wording or f"Choose {int(needed)} more credits",
                            "credits":             needed,
                            "is_pool":             True,
                            "pool_needed_credits": int(needed),
                            # An adviser-defined requirement can never be auto-filled,
                            # so the UI must ask the student rather than offer a picker.
                            "needs_confirmation":  gtype == "unstructured_credits",
                            "searchable":          gtype == "dept_credits",
                            # The requirement's FULL size, kept alongside the
                            # remaining `credits` so the confirm screen can show
                            # "6 of 9" once the student has confirmed part of it.
                            "requirement_credits": src.get("threshold"),
                        }
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

                        # A compound branch the student has already STARTED is a
                        # choice already made. PSU's "ACCTG 211 or (ACCTG 201 and
                        # ACCTG 202)" with 201 done means they owe 202 — not a
                        # fresh choice between 202 and 211. Schedule the rest of
                        # that branch and take the whole pair off the table, so
                        # the plan never offers the alternative they've passed on.
                        started = [it for it in items
                                   if it.get("pair_group_id") == pid
                                   and it.get("branch_status") == "partial"]
                        if started:
                            for it in started:
                                code = it.get("course_code", "")
                                if it.get("status") != "missing" or code in seen_codes:
                                    continue
                                seen_codes.add(code)
                                missing.append({
                                    "course_code":  code,
                                    "course_title": it.get("course_title", ""),
                                    "credits":      it.get("credits") or 3,
                                    "slot_key":     f"course:{_strip_w(code)}",
                                    "slot_kind":    "course",
                                })
                            for it in items:
                                if it.get("pair_group_id") == pid:
                                    seen_codes.add(it.get("course_code", ""))
                            continue
                        # Find the other option to label it
                        partner = next(
                            (it for it in items
                             if it.get("pair_group_id") == pid and it["course_code"] != item["course_code"]),
                            None,
                        )
                        # Two rows of the SAME branch are a combination, not a
                        # choice — "BIOL 114 and BIOL 115" (lecture + its lab).
                        # Rendering that as "or" tells the student to take one.
                        same_branch = (
                            partner is not None
                            and item.get("pair_branch_id")
                            and partner.get("pair_branch_id") == item.get("pair_branch_id")
                        )
                        joiner = "and" if same_branch else "or"
                        label = (
                            f"{item['course_code']} {joiner} {partner['course_code']}"
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


def _sort_named(courses: list[dict], priority: set[str] | None = None) -> list[dict]:
    """
    Order named (non-pool) missing courses so that:
      0. Entrance-to-Major courses come first. PSU expects the gate cleared by
         the end of the fourth semester, and a student who leaves one of these
         to senior year has not just taken a course late — they have missed the
         deadline to be admitted to the major at all. Within the gate the normal
         ordering still applies.
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

    def _base_code(code: str) -> str:
        return re.sub(r"[WHNMXY]$", "", (code or "").strip().upper()).strip()

    priority = priority or set()
    if priority:
        gate = [c for c in courses if _base_code(c.get("course_code", "")) in priority]
        rest = [c for c in courses if _base_code(c.get("course_code", "")) not in priority]
        if gate:
            return _sort_named(gate) + _sort_named(rest)

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


def _bulletin_record(code: str) -> dict | None:
    """The bulletin's {title, credits} for a code (keyed with its W suffix, e.g.
    'CHEM 423W'), falling back to the suffix-stripped form."""
    b = _bulletin_courses()
    code = code.strip().upper()
    return b.get(code) or b.get(re.sub(r"[WHNMXY]$", "", code).strip())


def _transcript_display_code(c: dict) -> str:
    """A transcript row's code as the student registered it. Storage strips the
    writing suffix into `is_writing` ('FRNSC 485W' -> 'FRNSC 485'), but a few
    suffixed courses are different courses from their bare twin — FRNSC 485W is
    4 cr 'Coalescence of Forensic Science Concepts', FRNSC 485 is 2 cr — so the
    card (and the course screen it opens) needs the suffix back. Take the letter
    the bulletin actually lists; with none listed, keep the stored code.
    A row that kept its registered code (raw_code, stored since the honors fix)
    shows exactly that — 'ENGL 137H', 'BIOL 230M'."""
    raw = (c.get("raw_code") or "").strip()
    if raw:
        return raw
    code = c.get("course_code", "")
    if c.get("is_writing") and code and code[-1].isdigit():
        b = _bulletin_courses()
        for sfx in "WMXY":
            if code + sfx in b:
                return code + sfx
    return code


def _fill_future_titles(semesters: list[dict]) -> None:
    """Backfill empty course_title on real (non-pool) recommended cards, and the
    title + credits of each dropdown option, so 'Plan your registration' shows
    names, not just codes. The bulletin is authoritative (catalog rows carry
    scraper junk like FRNSC 475 = 'Supporting Course (consult your adviser) *3');
    the catalog vote is the fallback for codes the bulletin doesn't list."""
    titles: dict[str, str] | None = None

    def title_for(code: str) -> str | None:
        nonlocal titles
        rec = _bulletin_record(code)
        if rec and rec.get("title"):
            return rec["title"]
        if titles is None:
            titles = _catalog_titles()
        return titles.get(code) or titles.get(re.sub(r"[WHNMXY]$", "", code).strip())

    for sem in semesters:
        for c in sem.get("courses", []):
            for o in c.get("options") or []:
                ocode = (o.get("course_code") or "").strip().upper()
                if not _REAL_CODE_RE.match(ocode):
                    continue
                rec = _bulletin_record(ocode)
                if rec and rec.get("credits") is not None:
                    o["credits"] = float(rec["credits"])
                if not o.get("course_title"):
                    o["course_title"] = title_for(ocode) or ""
            if c.get("course_title") or c.get("is_pool"):
                continue
            code = (c.get("course_code") or "").strip().upper()
            if " OR " in code or not _REAL_CODE_RE.match(code):
                continue
            t = title_for(code)
            if t:
                c["course_title"] = t


def _make_pool_selectable(entry: dict, pool_seq: int | None = None) -> None:
    """Give a bounded pool (a dropdown of >1 concrete course) a class-selector
    identity, so the student can say which of the listed courses they'll take
    rather than only reading the list."""
    opts = entry.get("pool_courses") or []
    if len(opts) < 2:
        return
    entry["slot_key"]  = _pool_slot_key(entry.get("course_code", ""), pool_seq)
    entry["slot_kind"] = "pool"
    entry["options"]   = opts


def _pool_slot_key(name: str, pool_seq: int | None = None) -> str:
    """Stable class-selector identity for a bounded requirement pool, derived from
    the requirement group's own name ('Supporting Courses' -> 'pool:SUPPORTING_COURSES').
    The name is what the catalog keys the group on, so it survives a reflow the way
    a course code does.

    One section can hold several pools, though (ETI's "Additional Courses" has
    four), and they would all collide on the section name — the student's pick
    for the speech pool would overwrite their pick for the programming pool in
    `user_course_choices`. `pool_seq` disambiguates them.

    The FIRST pool in a section deliberately keeps the bare, historic key: rows
    predating the column have no pool_seq, and pool #1 is the pool that key
    already referred to, so no stored choice is orphaned by this change."""
    tok = re.sub(r"[^A-Z0-9]+", "_", (name or "").strip().upper()).strip("_")
    base = f"pool:{tok or 'POOL'}"
    return base if not pool_seq or int(pool_seq) <= 1 else f"{base}@{int(pool_seq)}"


def _choice_for(mapping: dict[str, str] | None, slot_key: str | None) -> str | None:
    """A stored decision for this slot, tolerating the per-slice suffix.

    `_expand_pool` gives each slice of a split pool its own key ("pool:X#0",
    "pool:X#1") so a course picked for one slice doesn't appear on all of them.
    But a decision made somewhere that only knows the pool — the Entrance to
    Major checklist writes against the un-split key `_collect_missing` reports —
    would then match no slice at all and silently do nothing. Fall back to the
    base key so such a pick lands on the first slice."""
    if not mapping or not slot_key:
        return None
    return mapping.get(slot_key) or mapping.get(slot_key.split("#")[0])


def _apply_pool_choice(slot: dict, course_choices: dict[str, str] | None) -> None:
    """Fill a bounded pool slot with the course the student picked from its
    dropdown.  Display/scheduling only — the audit stays the source of truth for
    whether the pool is actually satisfied — so this mirrors the gen-ed pick:
    the placeholder becomes a real course card (title backfilled by
    `_fill_future_titles`) that keeps its `options` so the pick can be changed."""
    chosen = _choice_for(course_choices, slot.get("slot_key"))
    if not chosen:
        return
    opts = slot.get("options") or []
    if not any(_strip_w(chosen) == _strip_w(o.get("course_code", "")) for o in opts):
        return                              # stale pick (the pool changed) — ignore
    slot["chosen_code"]  = chosen
    slot["course_code"]  = chosen
    slot["course_title"] = ""
    slot["is_pool"]      = False


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
    for i, cr in enumerate(sizes):
        slot = dict(entry)
        slot["credits"] = cr
        # A split pool needs one slot_key per slice, else a course picked for the
        # first slice would show up on every one of them.
        if entry.get("slot_key") and len(sizes) > 1:
            slot["slot_key"] = f"{entry['slot_key']}#{i}"
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


# ── Prerequisite / corequisite ordering ──────────────────────────────────────
#
# Neither packer knew a course's prerequisites: the SAP rebalance sliced the
# template into even chunks across its semester boundaries (splitting ARCH 203
# from its corequisites AE 421 / ARCH 231), and a student who skipped ACCTG 211
# had FIN 301 pulled into the very term they make it up. `course_prereqs` holds
# PSU's published requisites; these helpers keep a course at least one term after
# a prerequisite still in the plan and no earlier than its corequisites.
#
# PSU's own plan overrides the bulletin: where a template puts a course in the
# same semester as its prerequisite (EBF 200 beside ECON 102) that pairing is
# allowed, and where it puts the course first the constraint is waived. A
# no-transcript student therefore still sees the official plan unchanged.

def _slot_codes(c: dict) -> set[str]:
    """Definite course codes a slot provides: 'MATH 140' or 'MATH 110 or MATH 140'.
    A pool / gen-ed placeholder provides none until a course is chosen for it."""
    raw = c.get("course_code") or ""
    out = set()
    for part in re.split(r"\s+or\s+", raw, flags=re.I):
        code = course_prereqs.norm(part)
        if re.fullmatch(r"[A-Z]{2,6}(?:-[A-Z]{1,4})? \d{1,3}[A-Z]?", code):
            out.add(code)
    return out


def _one_code(c: dict) -> str | None:
    """The slot's course when it names exactly one — only then are its own
    requisites known (a choose-one slot could become either course)."""
    codes = _slot_codes(c)
    return next(iter(codes)) if len(codes) == 1 else None


def _template_sem_index(template: dict | None) -> dict[str, int]:
    """course -> the first template semester that lists it."""
    out: dict[str, int] = {}
    for i, sem in enumerate((template or {}).get("semesters", [])):
        for slot in sem.get("slots", []):
            for code in ([slot["code"]] if slot.get("code") else (slot.get("codes") or [])):
                out.setdefault(course_prereqs.norm(code), i)
    return out


def _needs(code: str, done: set[str], tsem: dict[str, int] | None) -> list[tuple[frozenset, bool]]:
    """Unmet requisite clauses of `code` as (alternatives, strictly_earlier)."""
    pre, co = course_prereqs.constraints(code)
    out = []
    for alts, strict in [(a, True) for a in pre] + [(a, False) for a in co]:
        if alts & done:
            continue
        if tsem and code in tsem:
            placed = [tsem[a] for a in alts if a in tsem]
            if placed:
                if tsem[code] < min(placed):
                    continue            # PSU's plan puts this course first
                if tsem[code] == min(placed):
                    strict = False      # ... or in the same semester
        out.append((alts, strict))
    return out


def _requisite_needs(items: list[dict], done: set[str],
                     tsem: dict[str, int] | None) -> list[list[tuple[set[int], bool]]]:
    """Per item: [(indices of items that can meet the clause, strict)]. Clauses no
    item in the list can meet are dropped — nothing to order against. Mutual
    requirements (bad data, or cross-listed twins) are ignored."""
    providers: dict[str, set[int]] = defaultdict(set)
    for i, it in enumerate(items):
        for code in _slot_codes(it):
            providers[code].add(i)
    raw: list[list[tuple[set[int], bool]]] = []
    for i, it in enumerate(items):
        code = _one_code(it)
        clauses = []
        for alts, strict in (_needs(code, done, tsem) if code else []):
            js = set().union(*(providers.get(a, set()) for a in alts)) - {i}
            if js:
                clauses.append((js, strict))
        raw.append(clauses)
    # Drop a strict edge i -> j when j also strictly needs i: no order satisfies both.
    strict_on = [{j for js, s in cl if s for j in js} for cl in raw]
    return [[(js, s) for js, s in cl if not (s and all(i in strict_on[j] for j in js))]
            for i, cl in enumerate(raw)]


def _pack_ordered(items: list[dict], n: int, done: set[str] | None = None,
                  tsem: dict[str, int] | None = None, cap: float = _MAX_CREDITS) -> list[list[dict]]:
    """Split `items` into >= n ordered chunks the way `_slice_even` does, except that
    an item lands at least one chunk after a prerequisite still in the list and
    in the same chunk as (or after) its corequisites. With no requisites among
    the items this IS `_slice_even`."""
    if n <= 0 or not items:
        return []
    done = done or set()
    needs = _requisite_needs(items, done, tsem)
    if not any(needs):
        return _slice_even(items, n)

    ideal = [0] * len(items)
    for ci, idxs in enumerate(_slice_even(list(range(len(items))), n)):
        for i in idxs:
            ideal[i] = ci

    # Place in a stable topological order (lowest index first) so every requisite
    # still in the list is placed before the course that needs it. A corequisite
    # is "same term or earlier", so it is an ordering edge like any other — not a
    # bond: tying the two together makes a cycle as soon as one of them also has
    # a prerequisite on the other's side (BE 404 -> BE 301 -> MATH 251).
    deps = [{j for js, _ in needs[i] for j in js} for i in range(len(items))]
    order, placed = [], set()
    pending = list(range(len(items)))
    while pending:
        nxt = next((i for i in pending if deps[i] <= placed), pending[0])
        pending.remove(nxt)
        order.append(nxt)
        placed.add(nxt)

    # Critical path: a course with a chain of N courses still to follow it must be
    # done N terms before the end, or the chain spills into an extra semester
    # (DS 340W left in the final term pushes DS 440W past graduation).
    # Iterated to a fixpoint: mutual corequisites (KINES 366 / 464 / 468 each name
    # the others) form cycles a single pass would not settle.
    height = [0] * len(items)
    for _ in range(len(items)):
        changed = False
        for i in order:
            for js, strict in needs[i]:
                for j in js:      # a corequisite must be ready by the same term
                    h = height[i] + (1 if strict else 0)
                    if h > height[j]:
                        height[j], changed = h, True
        if not changed:
            break

    chunk_of: dict[int, int] = {}
    loads: dict[int, float] = defaultdict(float)
    named: dict[int, list] = defaultdict(list)       # (height, credits) of courses placed
    for i in order:
        latest = max(0, n - 1 - height[i])
        floor = 0
        for js, strict in needs[i]:
            at = [chunk_of[j] for j in js if j in chunk_of]
            if at:
                floor = max(floor, min(at) + (1 if strict else 0))
        target = max(min(ideal[i], latest), floor)
        cr = _display_credits(items[i])
        if target > ideal[i]:
            # Pushed later: don't pile onto a full semester.
            while loads[target] and loads[target] + cr > cap:
                target += 1
        elif target < ideal[i]:
            # Pulled earlier: placeholders there, and courses with more slack than
            # this one, can make room (the relief pass below moves them).
            while target < ideal[i] and sum(c for h, c in named[target]
                                            if h >= height[i]) + cr > _TARGET_CREDITS:
                target += 1
        chunk_of[i] = target
        loads[target] += cr
        if _slot_codes(items[i]):
            named[target].append((height[i], cr))

    # Placement only sees requisites placed before it, so a corequisite cycle can
    # land split. Raise every course to the first term its requisites allow.
    for _ in range(len(items)):
        changed = False
        for i in range(len(items)):
            for js, strict in needs[i]:
                at = min(chunk_of[j] for j in js) + (1 if strict else 0)
                if chunk_of[i] < at:
                    chunk_of[i], changed = at, True
        if not changed:
            break

    # Rebalance. Placeholders have no prerequisites and may sit in any term; a
    # course may move one term later when nothing that needs it is disturbed.
    n_chunks = max(chunk_of.values()) + 1
    cr_i = [_display_credits(it) for it in items]
    movable = [not _slot_codes(it) and not _is_internship(it) for it in items]
    load = lambda c: sum(cr_i[i] for i in chunk_of if chunk_of[i] == c)
    needed_by = defaultdict(list)
    for k, clauses in enumerate(needs):
        for js, strict in clauses:
            for j in js:
                needed_by[j].append((k, js, strict))

    def _can_delay(i: int, dest: int) -> bool:
        for k, js, strict in needed_by[i]:
            at = min(dest if j == i else chunk_of[j] for j in js)
            if chunk_of[k] < at + (1 if strict else 0):
                return False
        return True

    for c in range(n_chunks):
        guard = len(items)
        while load(c) > cap and guard:
            guard -= 1
            here = sorted((i for i in chunk_of if chunk_of[i] == c), reverse=True)
            ph = next((i for i in here if movable[i]), None)
            if ph is not None:
                room = [d for d in range(n_chunks) if d != c and load(d) + cr_i[ph] <= cap]
                if room:
                    chunk_of[ph] = min(room, key=load)
                    continue
            # Then move a course EARLIER, into the latest term with room its own
            # requisites allow — earlier never disturbs what depends on it.
            early = None
            for i in sorted(here, key=lambda i: (height[i], -i)):
                if movable[i]:
                    continue
                floor = max((min(chunk_of[j] for j in js) + (1 if st else 0)
                             for js, st in needs[i]), default=0)
                fits = [d for d in range(floor, c) if load(d) + cr_i[i] <= cap]
                if fits:
                    early = (i, fits[-1])
                    break
            if early:
                chunk_of[early[0]] = early[1]
                continue
            # Otherwise delay the course with the most slack; if that fills the next
            # term, its own turn in this loop passes the excess on.
            late = next((i for i in sorted(here, key=lambda i: (height[i], -i))
                         if not movable[i] and c + 1 < n_chunks and _can_delay(i, c + 1)), None)
            if late is None:
                break
            chunk_of[late] = c + 1

    # Refill semesters a pushed course left light with placeholders from later ones.
    per = sum(cr_i) / max(n, 1)
    for c in range(n_chunks):
        while load(c) < per - 1.5:
            src = next((i for i in sorted(chunk_of) if chunk_of[i] > c and movable[i]), None)
            if src is None or load(c) + cr_i[src] > cap:
                break
            chunk_of[src] = c

    chunks: list[list[dict]] = [[] for _ in range(n_chunks)]
    for i in range(len(items)):
        chunks[chunk_of[i]].append(items[i])
    return chunks


def _cr_of(items: list[dict]) -> float:
    return sum(_display_credits(it) for it in items)


def _enforce_prereq_order(future: list[dict], done: set[str],
                          tsem: dict[str, int] | None = None) -> list[dict]:
    """Final pass over the emitted plan: move any course sitting before (or, for a
    prerequisite, beside) a requisite that is still in the plan to the first term
    it may occupy, swapping a placeholder back so credits balance. Catches what
    the entrance hold and credential merge can disturb, on both timeline paths.
    Pinned courses are the student's decision and are left alone."""
    if not future:
        return future
    courses = lambda: [(i, c) for i, s in enumerate(future) for c in s["courses"]]
    moves = 0
    budget = 4 * sum(len(s["courses"]) for s in future)
    while moves < budget:
        flat = courses()
        items = [c for _, c in flat]
        needs = _requisite_needs(items, done, tsem)
        hit = None
        for k, (i, c) in enumerate(flat):
            if c.get("pinned"):
                continue
            need = i
            for js, strict in needs[k]:
                at = min(flat[j][0] for j in js)
                need = max(need, at + (1 if strict else 0))
            if need > i:
                hit = (i, c, need)
                break
        if not hit:
            break
        i, c, need = hit
        origin_summer = future[i]["term"].startswith("SU")
        while need < len(future) and future[need]["term"].startswith("SU") and not origin_summer:
            need += 1
        while need >= len(future):
            last = max((s["term"] for s in future), key=_term_key)
            future.append({"term": _next_term(last), "label": _term_label(_next_term(last)),
                           "status": "upcoming", "credits": 0.0, "courses": []})
        future[i]["courses"].remove(c)
        dest = future[need]
        filler = next((f for f in dest["courses"]
                       if _is_placeholder(f) and not _slot_codes(f) and not f.get("pinned")), None)
        if filler and _semester_credits(dest["courses"]) + float(c.get("credits_earned", 3) or 3) > _TARGET_CREDITS:
            dest["courses"].remove(filler)
            future[i]["courses"].append(filler)
        dest["courses"].append(c)
        c["moved_for_prerequisite"] = True
        moves += 1

    for s in future:
        s["credits"] = _semester_credits(s["courses"])
    return [s for s in future if s["courses"]]


FOCUS_UNCHOSEN_LABEL = "Application Focus (please select one)"


def _label_focus_slots(semesters: list[dict], focus: str | None, has_areas: bool) -> None:
    """Name the plan's unfilled Application Focus slots after the student's state.
    Before a focus is picked the slot is not a course choice at all — the student
    has to choose an area first — so it reads "please select one" and carries
    `needs_focus` (the app sends that tap to the Account page's focus picker, not
    to a course list mixing every area). After, it names the area. A slot the
    student already filled with a course keeps that course. Only majors with
    focus areas in the catalog are touched."""
    if not has_areas:
        return
    for sem in semesters:
        if sem.get("status") != "upcoming":
            continue
        for c in sem["courses"]:
            if c.get("pool_ref") != "application_focus" or not c.get("is_pool") or c.get("chosen_code"):
                continue
            if focus:
                c["course_code"] = f"{focus} course"
            else:
                c["course_code"] = FOCUS_UNCHOSEN_LABEL
                c["course_title"] = "Choose your focus area to see its courses"
                c["needs_focus"] = True


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
                # An adviser-defined credential requirement: shown in the bulletin's
                # own words and never auto-satisfied, so the UI asks the student
                # instead of offering a course picker.
                "needs_confirmation":  c.get("needs_confirmation", False),
                # The requirement's FULL size, alongside the remaining `credits_earned`,
                # so the confirm screen can show "6 of 9" once partly confirmed.
                "requirement_credits": c.get("requirement_credits"),
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
    done: set[str] | None = None,
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
    # Prerequisite-aware: a course lands after the prerequisites it still needs.
    named_alloc = _pack_ordered(named, n_sems, done) if named else [[] for _ in range(n_sems)]

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
    for s in range(max(n_sems, len(named_alloc))):
        chunk = list(named_alloc[s]) if s < len(named_alloc) else []
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


def _reflow_rebalance(records: list[dict], base_term: str, done: set[str] | None = None,
                      tsem: dict[str, int] | None = None) -> list[dict]:
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
    # Slicing the flattened template ignores its semester boundaries, so keep each
    # course after its prerequisites and beside its corequisites while packing.
    chunks = [c for c in _pack_ordered(academic, n_sems, done, tsem) if c]

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


def _reflow_template(records: list[dict], base_term: str, done: set[str] | None = None,
                     tsem: dict[str, int] | None = None) -> list[dict]:
    """Reflow matched SAP-template slots into future semesters.

    A no-transcript / on-track student (nothing satisfied) reproduces the
    published plan exactly (`_reflow_reproduce`).  A partially-complete student
    — who has already satisfied some slots — gets the remaining, prerequisite-
    ordered work re-packed into balanced semesters with the internship placed
    between junior and senior year (`_reflow_rebalance`), so graduation reflects
    the real remaining load rather than the template's now-lopsided groupings.
    """
    if any(r["satisfied"] for r in records):
        return _reflow_rebalance(records, base_term, done, tsem)
    return _reflow_reproduce(records, base_term)


def _build_layer1_future(
    audit_result: dict,
    gen_ed_result: dict,
    requirement_rows: list[dict],
    transcript_courses: list[dict],
    transfer_courses: list[dict],
    base_term: str,
    course_choices: dict[str, str] | None = None,
    gate_codes: set[str] | None = None,
    done: set[str] | None = None,
) -> list[dict]:
    """Layer 1 fallback: build future semesters from the audit alone (no SAP
    template) with the credit-band packer.  Used for every major that doesn't
    have a plan template."""
    collected     = _collect_missing(audit_result, course_choices)
    named_courses = _sort_named([c for c in collected if not c.get("is_pool")],
                                priority=gate_codes)
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
        for piece in _expand_pool(p):
            _apply_pool_choice(piece, course_choices)
            pool_slots.append(piece)

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
        done=done,
    )


def _merge_credential_slots(future: list[dict], credential_audits: list[dict],
                            course_choices: dict[str, str] | None = None) -> list[dict]:
    """Fold a declared minor's / certificate's remaining courses into the plan.

    Applied *after* both timeline paths converge, so the SAP-template path and the
    Layer 1 packer behave identically here: the major's plan is built first and stays
    authoritative, and credential work fills the remaining headroom.

    Slots keep a `credential` tag (the UI badges the course with it, so a student can
    see why a course they didn't expect is in their plan) and a `cred:`-prefixed
    `slot_key`, which the existing class-selector pin/swap machinery handles unchanged.

    A course the major already schedules is NOT added twice — it appears once and
    counts for both, which is the same double-count stance the audit takes.
    """
    if not credential_audits:
        return future                      # byte-identical no-op

    already = {
        (c.get("course_code") or "").strip().upper()
        for sem in future for c in sem.get("courses", [])
    }

    pending: list[dict] = []
    for cred in credential_audits:
        program = cred.get("program", "")
        short   = program.split(",")[0].strip()
        for slot in _collect_missing(cred, course_choices):
            code = (slot.get("course_code") or "").strip().upper()
            if not slot.get("is_pool") and code in already:
                continue
            already.add(code)

            # Split a departmental pool into ~3-credit slots the same way major pools
            # are split (_expand_pool), so a 6-credit minor requirement can fill the
            # headroom of two existing semesters instead of forcing a whole new term.
            # An adviser-defined requirement is NOT split: it is one block the student
            # settles with their adviser, and slicing it would misrepresent it.
            pieces = ([slot] if slot.get("needs_confirmation") or not slot.get("is_pool")
                      else _expand_pool(slot))

            for i, piece in enumerate(pieces):
                piece = dict(piece)
                # _expand_pool re-labels each slice generically; the bulletin's own
                # wording is the requirement, so keep it.
                if slot.get("course_title"):
                    piece["course_title"] = slot["course_title"]
                piece["credential"]       = program
                piece["credential_short"] = short
                base_key = slot.get("slot_key") or f"code:{code}"
                suffix   = f":{i}" if len(pieces) > 1 else ""
                piece["slot_key"] = f"credslot:{program}:{base_key}{suffix}"
                _apply_pool_choice(piece, course_choices)
                pending.append(piece)

    if not pending:
        return future

    # Fill the headroom in already-planned semesters before adding any new term —
    # a minor should lengthen the plan only when it genuinely cannot fit.
    for sem in future:
        if not pending:
            break
        # Skip summer. The plan deliberately avoids it (_next_term jumps SP->FA), and a
        # summer term that IS in the plan is there for a specific reason — the SAP path
        # lifts a required internship into one — so it is not spare capacity for a minor.
        if str(sem.get("term", "")).startswith("SU"):
            continue
        while pending and _semester_credits(sem["courses"]) + \
                float(pending[0].get("credits") or 3) <= _MAX_CREDITS:
            sem["courses"].append(_future_course(pending.pop(0)))
        sem["credits"] = _semester_credits(sem["courses"])

    # Anything left needs new terms.  Declaring a minor late genuinely can add a
    # semester; the client is told so via `added_terms` rather than finding a
    # mystery term in the plan.
    term = future[-1]["term"] if future else "FA 2026"
    while pending:
        term = _next_term(term)
        courses, credits = [], 0.0
        while pending and credits + float(pending[0].get("credits") or 3) <= _TARGET_CREDITS:
            slot = pending.pop(0)
            courses.append(_future_course(slot))
            credits += float(slot.get("credits") or 3)
        if not courses:                     # a single slot bigger than the target
            courses.append(_future_course(pending.pop(0)))
        # Built directly rather than through _emit_semester: these courses are already
        # in the mobile schema, and re-emitting would drop the `credential` tag.
        future.append({
            "term":    term,
            "label":   _term_label(term),
            "status":  "upcoming",
            "credits": _semester_credits(courses),
            "courses": courses,
        })

    return future


def _future_course(slot: dict) -> dict:
    """One credential slot in the mobile-facing course schema."""
    emitted = _emit_semester("X", [slot])["courses"][0]
    emitted["credential"]       = slot.get("credential")
    emitted["credential_short"] = slot.get("credential_short")
    return emitted


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
            target = _choice_for(pins, sk)
            if sk and target:
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


def _plan_codes(requirement_rows: list[dict], template: dict | None) -> list[str]:
    """Every course code the major names — catalog rows plus its SAP template, so
    a templated major with thin catalog rows still has a department."""
    codes = [r.get("course_code", "") for r in requirement_rows]
    for sem in (template or {}).get("semesters", []):
        for slot in sem.get("slots", []):
            codes += [slot["code"]] if slot.get("code") else list(slot.get("codes") or [])
    return codes


def _template_open_codes(template: dict | None, gate_codes: set[str]) -> set[str]:
    """Courses PSU's own plan schedules in or before its entrance semester (the
    last one holding a gate course). PSU would not recommend a course a student
    cannot yet register for, so these are open whatever their department —
    Supply Chain's plan puts SCM 301 beside FIN 301, Advertising's puts COMM 320
    in semester 2. The department heuristic is only a fallback beneath this."""
    sems = (template or {}).get("semesters", [])
    gate_codes = {entrance_to_major._base(c) for c in gate_codes}
    codes_by_sem = [
        {entrance_to_major._base(c) for slot in sem.get("slots", [])
         for c in ([slot["code"]] if slot.get("code") else (slot.get("codes") or []))}
        for sem in sems
    ]
    last = max((i for i, codes in enumerate(codes_by_sem) if codes & gate_codes), default=-1)
    return set().union(*codes_by_sem[:last + 1]) if last >= 0 else set()


def _is_placeholder(c: dict) -> bool:
    """A pool / gen-ed / elective slot — safe to move earlier, unlike a named
    course that may have prerequisites."""
    return bool(c.get("is_pool") or c.get("gen_ed_categories"))


def _eligible_in(c: dict, idx: int, future: list[dict], done: set[str],
                 tsem: dict[str, int] | None) -> bool:
    """Could course slot `c` sit in future[idx]? Its prerequisites must be done or
    planned in an EARLIER term, its corequisites no later than that term. A slot
    offering alternatives qualifies if any one of them does."""
    earlier = set(done)
    for s in future[:idx]:
        for x in s["courses"]:
            earlier |= _slot_codes(x)
    same = set().union(*(_slot_codes(x) for x in future[idx]["courses"])) if future[idx]["courses"] else set()
    codes = _slot_codes(c)
    if not codes:
        return True
    for code in codes:
        strict = [a for a, st in _needs(code, earlier, tsem) if st]
        co = [a for a, st in _needs(code, earlier | same, tsem) if not st]
        if not strict and not co:
            return True
    return False


def _hold_for_entrance(future: list[dict], gate: dict | None, depts: set[str],
                       past_semesters: int, open_codes: set[str] | None = None,
                       done: set[str] | None = None,
                       tsem: dict[str, int] | None = None) -> list[dict]:
    """Keep major-only courses out of semesters before the student is in the major.

    PSU's flow: the semester a student finishes their last Entrance to Major
    course is the semester they conditionally declare, and major-only courses
    open the semester AFTER. So the earliest a locked course may sit is the term
    after the last unmet gate course in the plan — earlier for a student who is
    ahead, later for one who is behind. A gate stating a minimum semester
    standing ("third-semester classification") can push that later still.

    A locked course found too early is swapped with a pool / gen-ed placeholder
    from the first semester it may occupy, so credit balance holds and no named
    course is pulled earlier than its prerequisites allow. Runs before pins: a
    student who pins a course early is making a decision we honour.

    Sets `gate["major_courses_from"]` to the first term locked courses may use.
    """
    if not gate or not gate.get("groups") or not depts or not future:
        return future

    gate_codes = {entrance_to_major._base(c)
                  for g in gate["groups"] for c in g.get("options", [])}
    # Never locked: the gate itself, plus whatever PSU's plan offers before entrance.
    open_codes = gate_codes | (open_codes or set())

    # Semester number of each future Fall/Spring term, continuing from the
    # transcript. Summer terms are neither counted nor used.
    regular = [s for s in future if not str(s.get("term", "")).startswith("SU")]
    number = {s["term"]: past_semesters + i + 1 for i, s in enumerate(regular)}

    # The semester the student declares: the last one holding a gate course they
    # still need. A gate already finished (or finishing this term) declares now.
    declare = past_semesters
    for group in gate["groups"]:
        if group.get("status") in ("done", "in_progress"):
            continue
        wanted = {entrance_to_major._base(c) for c in group.get("options", [])}
        found = next((number[s["term"]] for s in regular
                      if any(wanted & entrance_to_major.slot_codes(c) for c in s["courses"])),
                     None)
        if found:                           # a gate course the plan never schedules
            declare = max(declare, found)   # (e.g. a gen-ed one) can't be placed
    unlock = max(declare + 1, gate.get("semester_standing") or 0)

    gate["major_courses_from"] = next(
        (s["term"] for s in regular if number[s["term"]] == unlock), None)

    early = [s for s in regular if number[s["term"]] < unlock]
    late  = [s for s in regular if number[s["term"]] >= unlock]

    def _locked(c: dict) -> bool:
        if c.get("entrance_to_major"):
            return False
        codes = entrance_to_major.slot_codes(c)
        # Every alternative must be locked — a slot offering one open option can
        # be filled with it before entrance.
        return bool(codes) and all(
            entrance_to_major.is_major_locked(code, depts, open_codes) for code in codes)

    held: list[tuple[dict, dict]] = []
    for sem in early:
        keep = []
        for c in sem["courses"]:
            if _locked(c):
                c["held_for_entrance"] = True
                held.append((c, sem))
            else:
                keep.append(c)
        sem["courses"] = keep
    if not held:
        return future

    for c, origin in held:
        cr = float(c.get("credits_earned", 3) or 3)
        placed = False
        for sem in late:
            filler = next((f for f in sem["courses"]
                           if _is_placeholder(f) and not f.get("pinned")
                           and not _locked(f)), None)
            load = _semester_credits(sem["courses"])
            if filler and load - float(filler.get("credits_earned", 3) or 3) + cr <= _MAX_CREDITS:
                sem["courses"].remove(filler)
                origin["courses"].append(filler)
            elif load + cr > _MAX_CREDITS:
                # Full, with no placeholder to trade: trade an open course the
                # student can take in the vacated term instead of skipping ahead.
                # Skipping cost an ETI student a semester — ETI 302 fell past a
                # full fall, and ETI 420 → 421 slid a term behind it.
                oi = future.index(origin)
                swap = next((f for f in sem["courses"]
                             if not f.get("pinned") and not _locked(f) and not _is_placeholder(f)
                             and load - float(f.get("credits_earned", 3) or 3) + cr <= _MAX_CREDITS
                             and _eligible_in(f, oi, future, done or set(), tsem)), None)
                if not swap:
                    continue
                sem["courses"].remove(swap)
                origin["courses"].append(swap)
            else:
                # No placeholder to trade back: pull forward a course the student
                # CAN take in the vacated term — not major-locked, not pinned, its
                # prerequisites met by then. Without this an ETI student whose ETI
                # 301/302 waited for entrance was left a 9-credit spring while BA 302
                # and ENGL 202C, open to them now, sat a semester later.
                oi = future.index(origin)
                pull = next(((ls, f) for ls in late if not ls["term"].startswith("SU")
                             for f in ls["courses"]
                             if not f.get("pinned") and not _locked(f) and not _is_placeholder(f)
                             and f is not c and _eligible_in(f, oi, future, done or set(), tsem)),
                            None)
                if pull:
                    pull[0]["courses"].remove(pull[1])
                    origin["courses"].append(pull[1])
            sem["courses"].append(c)
            placed = True
            break
        if not placed:
            # Nowhere left in the plan: holding the course costs a semester.
            term = _next_term(max((s["term"] for s in future), key=_term_key))
            sem = {"term": term, "label": _term_label(term), "status": "upcoming",
                   "credits": 0.0, "courses": [c]}
            future.append(sem)
            late.append(sem)

    for sem in future:
        sem["credits"] = _semester_credits(sem["courses"])
    return [s for s in future if s["courses"]]


def _chosen_first(future: list[dict], done: set[str],
                  tsem: dict[str, int] | None = None) -> list[dict]:
    """Within one requirement pool, a slot the student has picked a course for
    comes before a still-blank one. The packer shuffles blank placeholders freely
    to balance credits while a picked slot, now a named course, keeps its template
    position — so an ETI student's chosen BA 301 sat in SP 2028 behind a blank
    Application Focus slot in SP 2027. Swaps positions (equal credits, so loads
    hold) only where the picked course's prerequisites are met in the earlier term."""
    def family(c: dict) -> str | None:
        key = c.get("slot_key") or ""
        return key.split("#")[0] if c.get("slot_kind") == "pool" and "#" in key else None

    for si, sem in enumerate(future):
        for bi, blank in enumerate(sem["courses"]):
            fam = family(blank)
            if not fam or blank.get("chosen_code") or blank.get("pinned"):
                continue
            cr = float(blank.get("credits_earned", 3) or 3)
            for later in future[si + 1:]:
                pick = next((c for c in later["courses"]
                             if family(c) == fam and c.get("chosen_code") and not c.get("pinned")
                             and float(c.get("credits_earned", 3) or 3) == cr
                             and _eligible_in(c, si, future, done, tsem)), None)
                if pick:
                    later["courses"][later["courses"].index(pick)] = blank
                    sem["courses"][bi] = pick
                    break
    return future


def _mark_movable_terms(future: list[dict], done: set[str],
                        tsem: dict[str, int] | None = None,
                        locked=None, unlock_term: str | None = None) -> None:
    """Give every upcoming slot `movable_terms`: the Fall/Spring terms (plus one
    past the plan's end) the student may pin it to without breaking the plan.

    A term is allowed when each of the course's prerequisites is done or planned
    in an earlier term (a corequisite: no later), when no course planned later
    that needs it would then come first, and — for a major-only course — when the
    term is not before the student can be in the major. Slots offering
    alternatives take the loosest of them. Placeholders may go anywhere. Its own
    term is always allowed. Summer terms are never offered: a summer term in the
    plan is there for a reason (an internship)."""
    regular = [s["term"] for s in future if not s["term"].startswith("SU")]
    if not regular:
        return
    options = regular + [_next_term(max(regular, key=_term_key))]
    placed = [(c, s["term"]) for s in future for c in s["courses"]]
    where: dict[str, list[str]] = defaultdict(list)
    for c, term in placed:
        for code in _slot_codes(c):
            where[code].append(term)
    k = _term_key

    def _clause_ok(alts, strict: bool, t: str, skip: dict) -> bool:
        if alts & done:
            return True
        return any((k(p) < k(t)) if strict else (k(p) <= k(t))
                   for a in alts for p in where.get(a, []) if not (a in skip))

    for c, term in placed:
        if not c.get("slot_key"):
            continue
        codes = _slot_codes(c)
        if not codes:
            c["movable_terms"] = list(options)
            continue
        own = {code: True for code in codes}

        def _fits(t: str) -> bool:
            if locked and unlock_term and locked(c) and k(t) < k(unlock_term):
                return False
            # Its own prerequisites — any one alternative of the slot may qualify.
            if not any(all(_clause_ok(alts, st, t, own)
                           for alts, st in _needs(code, done, tsem)
                           if alts & set(where) or alts & done)
                       for code in codes):
                return False
            # Courses that need it: moving it must not strand one of them. A slot
            # offering alternatives is stranded only if every alternative is.
            for d, td in placed:
                if d is c:
                    continue

                def _viable(dcode: str, at: str) -> bool:
                    # Every requisite of `dcode` met, with this slot's courses at `at`.
                    for alts, st in _needs(dcode, done, tsem):
                        if alts & done or not (alts & (set(where) | codes)):
                            continue
                        spots = [at if a in codes else p
                                 for a in alts for p in ([at] if a in codes else where.get(a, []))]
                        if not any((k(p) < k(td)) if st else (k(p) <= k(td)) for p in spots):
                            return False
                    return True

                dcodes = _slot_codes(d)
                if (dcodes and any(_viable(x, term) for x in dcodes)
                        and not any(_viable(x, t) for x in dcodes)):
                    return False
            return True

        if _is_internship(c):
            c["movable_terms"] = [term]
            continue
        c["movable_terms"] = [t for t in options if t == term or _fits(t)]


def _relieve_overload(future: list[dict]) -> list[dict]:
    """Move pool / gen-ed placeholders out of a term above the target load into
    the lightest LATER Fall/Spring term that stays within it. The entrance hold
    trades placeholders back into the term it empties, so an ETI student had both
    Application Focus slots stacked into an 18-credit spring while their last two
    terms held 6 and 3. Moving a placeholder later can't break a prerequisite."""
    regular = [s for s in future if not str(s.get("term", "")).startswith("SU")]
    for i, sem in enumerate(regular):
        for f in list(sem["courses"]):
            if _semester_credits(sem["courses"]) <= _TARGET_CREDITS:
                break
            if not _is_placeholder(f) or f.get("pinned"):
                continue
            cr = float(f.get("credits_earned", 3) or 3)
            dest = min((s for s in regular[i + 1:]
                        if _semester_credits(s["courses"]) + cr <= _TARGET_CREDITS),
                       key=lambda s: _semester_credits(s["courses"]), default=None)
            if dest:
                sem["courses"].remove(f)
                dest["courses"].append(f)
    for sem in future:
        sem["credits"] = _semester_credits(sem["courses"])
    return future


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
                    "course_code":    _transcript_display_code(c),
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
    has_focus_areas = any(r.get("focus_area") for r in requirement_rows)
    requirement_rows = _filter_rows(requirement_rows, subplan, taken_codes, user.get("focus"))

    # A published-plan template renders the timeline on its own (it uses the
    # transcript + gen-ed audit, not the major's requirement rows), so a major
    # with a template but thin/empty catalog requirements must NOT 404 — only a
    # major with neither is a real dead end.
    template = load_template(major, subplan)
    # A declared Schreyer Scholar's thesis stands in for the electives their
    # department lets it replace (ME: 494H + 493 for an ETE + a GTE).
    template = apply_thesis_rule(template, user)
    if not requirement_rows and not template:
        raise HTTPException(
            status_code=404,
            detail=f"No requirements found for major: {major}. "
                   "Re-seed the database (setup_tables → load_catalog → seed_gen_ed → seed_matthew).",
        )
    # Student-declared substitutions ("my ESC 120 counts for CHE 100") are
    # per-user course equivalences (substitutions.py) applied to the taken-set,
    # so a substituted requirement stops being scheduled here just as a
    # cross-listed one does.
    declared_subs = get_substitutions(user_id)
    audit_result = run_audit(requirement_rows, transcript_courses, declared_subs)

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
        run_gen_ed_audit(gen_ed_rows, transcript_courses, declared_subs)
        if gen_ed_rows else {"groups": []}
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

    # Entrance-to-Major courses are scheduled first on the Layer 1 path and
    # badged on both. The SAP path needs no reordering — PSU's own plan already
    # puts the gate in the first two years, which is the whole point of it.
    gate_codes = entrance_to_major.priority_codes(major)

    # Courses whose requisites are already met: everything done, in progress or
    # transferred (with equivalences), plus requirements the audit counts as met.
    done_codes = {course_prereqs.norm(c) for c in
                  build_taken_set(transcript_courses, declared_subs)
                  | build_satisfied_req_codes(audit_result)}
    tsem = _template_sem_index(template)

    if template:
        # The major audit is the source of truth for course equivalences/pairs
        # (MATH 110/140, STAT 200/SCM 200): fold its satisfied requirement codes
        # into the taken set so the template stops re-scheduling met requirements.
        taken = (build_taken_set(transcript_courses, declared_subs)
                 | build_satisfied_req_codes(audit_result))
        records = match_template(
            template,
            taken,
            build_gen_ed_satisfied(gen_ed_result),
            transcript_courses=transcript_courses,
            used_codes=build_used_codes(audit_result, gen_ed_result),
            major_pool_codes=build_major_pool_codes(audit_result, template),
            gen_ed_courses=build_gen_ed_courses(gen_ed_result),
            course_choices=course_choices,
            gen_ed_open=build_gen_ed_open(gen_ed_result),
        )
        future = _reflow_template(records, base_term, done_codes, tsem)
    else:
        future = _build_layer1_future(
            audit_result, gen_ed_result, requirement_rows,
            transcript_courses, transfer_courses, base_term,
            course_choices=course_choices,
            gate_codes=gate_codes,
            done=done_codes,
        )

    # Declared minors / certificates schedule after the major's plan is built, so the
    # major stays authoritative and credential work fills the headroom left over.
    credential_audits = audit_declared_credentials(
        user, transcript_courses, declared_subs,
        credential_choices.get_credential_choices(user_id))
    terms_before = len(future)
    future = _merge_credential_slots(future, credential_audits, course_choices)
    # Declaring a credential can genuinely push graduation out. Report it so the client
    # can say so, rather than letting an extra term appear in the plan unexplained.
    credential_added_terms = max(0, len(future) - terms_before)

    # Badge gate courses wherever they landed, on both paths, so the client can
    # say WHY a course matters rather than just when to take it.
    if gate_codes:
        def _slot_hits_gate(slot: dict) -> bool:
            # A choose-one slot carries its alternatives in one label
            # ("IST 110 or CYBER 100"), and a pool slot lists them in `options`.
            # Any alternative that clears the gate makes the slot a gate slot.
            raw = (slot.get("course_code") or "")
            candidates = [c for c in re.split(r"\s+or\s+", raw, flags=re.I) if c]
            candidates += [o.get("course_code", "") for o in (slot.get("options") or [])]
            for cand in candidates:
                code = re.sub(r"[WHNMXY]$", "", cand.strip().upper()).strip()
                if code in gate_codes:
                    return True
                # The catalog and the gate can spell the same course
                # differently — Materials Science lists MATH 141G where its gate
                # says MATH 141, Vet/Biomed lists BIOL 114 where its gate says
                # BIOL 114H. Tolerate one trailing letter either way, the same
                # section-letter allowance sap_schedule._codes_match makes.
                if any(g == code[:-1] or code == g[:-1] for g in gate_codes
                       if g and code):
                    return True
            return False

        for term in future:
            for slot in term.get("courses", []):
                if _slot_hits_gate(slot):
                    slot["entrance_to_major"] = True

    # The gate, with each unmet group pointing at the slot that can satisfy it.
    # Built from `future` because these are the slots the student actually sees;
    # a key from anywhere else would be written and never read.
    gate = entrance_to_major.attach_slots(
        entrance_to_major.evaluate(major, transcript_courses, declared_subs),
        [c for term in future for c in term.get("courses", [])],
    )

    # Major-only courses wait until the semester after the gate is finished.
    depts = entrance_to_major.major_depts(_plan_codes(requirement_rows, template))
    open_codes = _template_open_codes(template, gate_codes)
    future = _hold_for_entrance(
        future, gate, depts,
        sum(1 for t in sorted_terms if t.split()[0] in ("FA", "SP")),
        open_codes, done_codes, tsem,
    )

    # Last word on order: nothing before a prerequisite or apart from a corequisite
    # still in the plan, whatever the hold / credential merge above did.
    future = _enforce_prereq_order(future, done_codes, tsem)
    # Only when the hold moved something: a plan it left alone (every fresh
    # student in a templated major) stays exactly PSU's.
    if any(c.get("held_for_entrance") for s in future for c in s["courses"]):
        future = _relieve_overload(future)
    future = _chosen_first(future, done_codes, tsem)

    future = _apply_pins(future, pins)

    # Where each course may be moved (the class selector's semester chips).
    gate_open = {entrance_to_major._base(c) for g in (gate or {}).get("groups", [])
                 for c in g.get("options", [])} | (open_codes or set())

    def _locked(c: dict) -> bool:
        if c.get("entrance_to_major"):
            return False
        codes = entrance_to_major.slot_codes(c)
        return bool(codes) and all(entrance_to_major.is_major_locked(x, depts, gate_open)
                                   for x in codes)

    _mark_movable_terms(future, done_codes, tsem, _locked,
                        (gate or {}).get("major_courses_from"))
    semesters.extend(future)

    # Recommended courses often come from major rows with no title — fill from the
    # cross-program catalog so Home/Timeline show names next to the codes.
    _fill_future_titles(semesters)
    _label_focus_slots(semesters, user.get("focus"), has_focus_areas)

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
        # Strictly additive: an older mobile build ignores this, and a student who
        # has declared nothing gets an empty list.
        "credential_added_terms": credential_added_terms,
        "credentials":         [
            {
                "program":           c["program"],
                "kind":              c["kind"],
                "remaining":         c["missing"],
                "manual_credits":    c["manual_credits"],
            }
            for c in credential_audits
        ],
        # Entrance to Major, each unmet group carrying the slot_key the checklist
        # writes a course pick / optional semester against. `None` for the 18
        # majors that publish no gate; an older build ignores the key.
        "entrance_to_major":   gate,
    }
