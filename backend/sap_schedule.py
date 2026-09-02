"""
SAP hybrid scheduling — the match stage.

`match_template()` walks a Suggested Academic Plan template (see plan_templates.py)
in order and decides, for each slot, whether the student has already satisfied it.
Satisfied slots fall out of the plan (they live in the transcript history);
unsatisfied slots become schedulable items the timeline's reflow stage places into
future semesters.

The audit engine remains the source of truth: this module only consumes a taken-set
derived from the transcript (with course equivalences) and the gen-ed audit's
per-category satisfaction — it does not re-implement degree rules.

Pure and DB-free so it can be unit-tested directly; the timeline layer builds the
`taken` set and `gen_ed_satisfied` map from live data and calls in.
"""

import re

from plan_templates import iter_slots
import business_breadth as _bb

try:  # course renames / cross-listings (IST→ETI, etc.) so a taken course still matches
    from audit_engine import _EQUIVALENCE_PAIRS
except Exception:  # pragma: no cover - audit engine always importable in practice
    _EQUIVALENCE_PAIRS = []

# Attribute suffixes PSU appends that don't change course identity for matching.
_ATTR_SUFFIX = "WHNMXYRSU"


def _norm(code: str) -> str:
    return re.sub(r"\s+", " ", (code or "").strip().upper())


def _base(code: str) -> str:
    """Strip one trailing attribute letter (W/H/N/…) so 'ACCTG 403W' → 'ACCTG 403'.
    A single trailing section-ish letter after a digit is removed only if it's an
    attribute letter; genuine section letters (A/B/C/D) are preserved."""
    c = _norm(code)
    m = re.match(rf"^([A-Z]+ \d+)[{_ATTR_SUFFIX}]$", c)
    return m.group(1) if m else c


def _codes_match(a: str, b: str) -> bool:
    """Whether two course codes refer to the same course, tolerant of attribute
    suffixes and a single section letter (catalog 'CAS 100A' vs SAP 'CAS 100')."""
    ba, bb = _base(a), _base(b)
    if ba == bb:
        return True
    lo, hi = sorted((ba, bb), key=len)
    # section-letter case: the longer is the shorter + exactly one trailing letter
    return len(hi) == len(lo) + 1 and hi.startswith(lo) and hi[-1].isalpha()


def _build_equiv_map() -> dict[str, set[str]]:
    m: dict[str, set[str]] = {}
    for a, b in _EQUIVALENCE_PAIRS:
        na, nb = _base(a), _base(b)
        m.setdefault(na, set()).add(nb)
        m.setdefault(nb, set()).add(na)
    return m


_EQUIV = _build_equiv_map()


def _equivalents(code: str) -> set[str]:
    b = _base(code)
    return {b} | _EQUIV.get(b, set())


def build_taken_set(transcript_courses: list[dict],
                    substitutions: dict | None = None) -> set[str]:
    """Base course codes the student has completed or is taking, expanded with
    known equivalences so a renamed/cross-listed course still matches a template.
    Transfer credit counts — the audit engine treats it as done.

    `substitutions` (requirement_code -> substitute_course, see substitutions.py)
    are the student's own declared equivalences and expand the set the same way a
    catalog equivalence does — but only when the substitute course is genuinely
    taken, so a stale declaration can't satisfy a template slot on its own."""
    taken: set[str] = set()
    for c in transcript_courses:
        if c.get("status") in ("done", "in_progress", "transfer"):
            taken |= _equivalents(c.get("course_code", ""))
    for req_code, sub_code in (substitutions or {}).items():
        if _base(sub_code) in taken:
            taken |= _equivalents(req_code)
    return taken


def is_taken(code: str, taken: set[str]) -> bool:
    """Whether a template code is satisfied by the taken set (equivalence- and
    section-letter-aware)."""
    for cand in _equivalents(code):
        if any(_codes_match(cand, t) for t in taken):
            return True
    return False


def _match_option(codes: list[str], taken: set[str], consumed: set[str]):
    """Return the taken token that satisfies one of `codes` and isn't already
    consumed, or None.  Consumption stops a single taken course from satisfying
    two template slots (e.g. 'BLAW 341 / BA 342' listed in two semesters — taking
    BA 342 covers one, not both)."""
    for code in codes:
        for cand in _equivalents(code):
            for t in taken:
                if t not in consumed and _codes_match(cand, t):
                    return t
    return None


def _gen_ed_category(group_name: str) -> str:
    """Leading category token of a gen-ed group name: 'US: United States Cultures'
    → 'US'; 'GN: Natural Sciences' → 'GN'; 'Communication: Effective Speech' →
    'COMMUNICATION'."""
    return _norm(group_name).split(":")[0].split()[0]


def build_gen_ed_satisfied(gen_ed_result: dict) -> dict[str, bool]:
    """Map gen-ed category token → satisfied, from a run_gen_ed_audit result."""
    out: dict[str, bool] = {}
    for g in (gen_ed_result or {}).get("groups", []):
        out[_gen_ed_category(g.get("name", ""))] = bool(g.get("satisfied"))
    return out


def build_satisfied_req_codes(*audit_results: dict) -> set[str]:
    """Base codes of every requirement an audit reports SATISFIED — completed,
    in-progress, or covered by a done/in-progress pair alternative.

    The audit engine (the source of truth) knows equivalences the template
    matcher doesn't: catalog `pair_group` alternatives (MATH 110 / MATH 140,
    STAT 200 / SCM 200) and course renames.  Folding the satisfied requirement
    *codes* into the taken set lets a template slot named `MATH 110` match a
    student who actually took the paired MATH 140 — so the timeline stops
    re-scheduling a requirement the audit already considers met.

    Likewise, every code in a SATISFIED choose_credits / choose_courses pool is
    included: the catalog may model options as one pool (IST 140 / IST 110 /
    CYBER 100 / CMPSC 121-132 in a "choose N credits" group) that the template
    lists as individual slots — once the pool is met (e.g. via CMPSC 131), the
    template must not re-schedule its other options."""
    out: set[str] = set()
    for res in audit_results:
        for g in (res or {}).get("groups", []):
            for src in (g.get("sub_groups") or [g]):
                gtype = src.get("sub_type") or src.get("group_type", "")
                pool_met = (gtype in ("choose_credits", "choose_courses")
                            and src.get("satisfied"))
                for it in src.get("items", []):
                    if (pool_met
                            or it.get("status") in ("done", "in_progress")
                            or it.get("pair_status") in ("done", "in_progress")):
                        out.add(_base(it.get("course_code", "")))
    return out


def build_gen_ed_courses(gen_ed_result: dict) -> list[str]:
    """Distinct base codes of the courses the gen-ed audit counts as completed
    or in-progress, in first-seen order.  These fill the template's category-less
    generic gen-ed slots (see `_assign_generic_gen_ed`)."""
    out: list[str] = []
    seen: set[str] = set()
    for g in (gen_ed_result or {}).get("groups", []):
        for it in g.get("items", []):
            if it.get("status") in ("done", "in_progress"):
                b = _base(it.get("course_code", ""))
                if b and b not in seen:
                    seen.add(b)
                    out.append(b)
    return out


def build_gen_ed_open(gen_ed_result: dict) -> bool:
    """Whether the student still has gen-ed work a picker could offer them — i.e.
    any of the searchable domain pools (GA/GN/GH/GS/GHW/GQ/US/IL, the
    `choose_credits` groups) is still unmet.

    A PSU bulletin plan lists most gen-ed credits as category-less "General
    Education" cells.  `_assign_generic_gen_ed` retires one per completed gen-ed
    course, but a student who covered eight domains with fewer courses (interdomain
    courses count twice) is left with generic slots the class selector has nothing
    to fill — every domain chip is gone, so the picker opens empty.  When no domain
    is open, those slots are phantom and get dropped.
    """
    for g in (gen_ed_result or {}).get("groups", []):
        if g.get("group_type") == "choose_credits" and not g.get("satisfied"):
            return True
    return False


def build_used_codes(*audit_results: dict) -> set[str]:
    """Base codes of every course an audit consumed (major and/or gen-ed result).
    Surplus detection subtracts these so a course that filled a requirement the
    template doesn't itemize can't also count toward a free-elective slot."""
    used: set[str] = set()
    for res in audit_results:
        for g in (res or {}).get("groups", []):
            for item in g.get("items", []):
                if item.get("status") in ("done", "in_progress"):
                    used.add(_base(item.get("course_code", "")))
    return used


# ── Slot → schedulable timeline item ─────────────────────────────────────────

def _dedupe_crosslisted(codes: list[str]) -> list[str]:
    """Drop the later of two ADJACENT codes sharing an identical catalog
    number+suffix under different depts (ENGL 137H / CAS 137H) — one cross-listed
    course printed under both subject codes.  Adjacency guards against
    coincidental number matches in long elective lists (AGECO 122 vs METEO 122).
    Display-only: match_template still consumes the slot's full code list."""
    out: list[str] = []
    for c in codes:
        parts, prev = c.split(" "), out[-1].split(" ") if out else None
        if (prev and len(parts) == 2 and len(prev) == 2
                and parts[1] == prev[1] and parts[0] != prev[0]):
            continue
        out.append(c)
    return out


def _choose_one_label(codes: list[str]) -> str:
    # Mobile CourseRow splits on ' or ' for pair routing; keep it readable.
    return " or ".join(_dedupe_crosslisted(codes)) if codes else ""


def slot_to_item(slot: dict) -> dict:
    """Convert an unsatisfied template slot into a schedulable item shaped like the
    timeline's course/pool dicts (so the existing packer / _emit_semester consume
    it unchanged)."""
    t = slot.get("type")
    credits = float(slot.get("credits", 3) or 3)

    if t == "course":
        return {"course_code": slot["code"], "course_title": slot.get("title", ""),
                "credits": credits}

    if t == "choose_one":
        return {"course_code": _choose_one_label(slot.get("codes", [])),
                "course_title": slot.get("title", ""), "credits": credits}

    if t == "gen_ed":
        cat = slot.get("category")
        if cat:
            return {"course_code": cat, "course_title": f"Choose a {cat} course",
                    "credits": credits, "is_pool": True, "gen_ed_categories": [cat]}
        return {"course_code": "General Education",
                "course_title": "Choose a general education course",
                "credits": credits, "is_pool": True, "gen_ed_categories": None}

    if t == "pool":
        title = f"Choose {int(credits)} credit(s)"
        if slot.get("ref") == "dept_level" and slot.get("dept"):
            title = f"Choose a {slot.get('level', 400)}-level {slot['dept']} course"
        return {"course_code": slot.get("label", "Requirement"),
                "course_title": title,
                "credits": credits, "is_pool": True,
                "pool_needed_credits": int(credits) if float(credits).is_integer() else credits,
                "pool_ref": slot.get("ref")}

    # elective
    return {"course_code": slot.get("label", "Elective"),
            "course_title": "Free elective", "credits": credits, "is_pool": True,
            "pool_needed_credits": int(credits) if float(credits).is_integer() else credits}


# ── Un-anchored pools & free electives ───────────────────────────────────────

# PSU world-language subject codes (PSU-specific — add to the multi-school rework
# list).  Deliberately conservative: a dept missing here just leaves the slot
# scheduled (today's behavior), while a wrong entry would falsely satisfy it.
_WORLD_LANGUAGE_DEPTS = {
    "ARAB", "ASL", "CHNS", "FR", "GER", "GREEK", "HEBR", "IT", "JAPNS", "KOR",
    "LATIN", "PORT", "RUS", "SPAN", "UKR",
}

def _dept(course: dict) -> str:
    return _norm(course.get("course_code", "")).split(" ")[0]


def _course_credits(course: dict) -> float:
    return float(course.get("credits_earned") or course.get("credits") or 3)


def _leftover_courses(transcript_courses: list[dict], consumed: set[str],
                      used_codes: set[str]) -> list[dict]:
    """Transcript courses neither a template slot nor an audit consumed — the
    surplus available for world-language slots and free electives."""
    claimed = consumed | used_codes
    out = []
    for c in transcript_courses:
        if c.get("status") not in ("done", "in_progress", "transfer"):
            continue
        toks = _equivalents(c.get("course_code", ""))
        if any(_codes_match(t, u) for t in toks for u in claimed):
            continue
        out.append(c)
    return out


_WORD_LEVELS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _slot_language_level(slot: dict) -> int | None:
    """Proficiency level a world-language slot demands, parsed from its label:
    'World Language Level 3', 'Level Two (8th credit level)', 'World Language 2'.
    None when the label carries no level (bare 'World Language')."""
    low = (slot.get("label") or "").lower()
    m = re.search(r"\blevel[\s-]*(one|two|three|four|five|\d{1,2})\b", low)
    if m:
        tok = m.group(1)
        return int(tok) if tok.isdigit() else _WORD_LEVELS[tok]
    m = re.search(r"\bworld language\s+(\d{1,2})\b", low)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\s+credit\s+level\b", low)
    if m:
        return max(1, -(-int(m.group(1)) // 4))   # 12th credit level → level 3
    return None


def _language_level(course: dict) -> int:
    """Proficiency level a completed language course attests.  PSU numbers the
    basic sequence 1/2/3 (each = 4 credit levels); 100-level is the 4th course,
    200+ the 5th.  Generic transfer placeholders ('SPAN XFRIL') carry no number —
    estimate from credits (4 credits per level, capped at the basic sequence)."""
    n = _course_number(course)
    if 1 <= n <= 3:
        return n
    if 100 <= n < 200:
        return 4
    if n >= 200:
        return 5
    return min(3, int(_course_credits(course) // 4))


def _assign_world_language(records: list[dict], leftovers: list[dict]) -> None:
    """Satisfy un-anchored world-language pool slots from leftover language
    courses.  A language requirement is one language's sequence, so only the
    dept the student has the most courses in is used (most courses, then
    alphabetical, for determinism).

    PSU language requirements are PROFICIENCY levels, not per-course seat time:
    a student who placed into SPAN 3 and passed it has completed the 12th-credit
    level, whatever the number of courses on the transcript.  Each slot's
    required level comes from its label (falling back to its position in the
    plan: 1st slot = level 1); a slot is satisfied when the student's highest
    attained level reaches it.  One consumed course per satisfied slot (highest
    level first) is removed from the elective surplus, mirroring the old
    one-course-per-slot bookkeeping."""
    slots = [r for r in records if not r["satisfied"]
             and r["slot"].get("type") == "pool"
             and r["slot"].get("ref") == "world_language"]
    by_dept: dict[str, list[dict]] = {}
    for c in leftovers:
        if _dept(c) in _WORLD_LANGUAGE_DEPTS:
            by_dept.setdefault(_dept(c), []).append(c)
    if not slots or not by_dept:
        return
    dept = sorted(by_dept, key=lambda d: (-len(by_dept[d]), d))[0]
    courses = sorted(by_dept[dept], key=_language_level, reverse=True)
    attained = _language_level(courses[0])
    satisfied_count = 0
    for i, rec in enumerate(slots):
        required = _slot_language_level(rec["slot"]) or (i + 1)
        if attained >= required:
            match = next((c for c in courses if _language_level(c) == required),
                         courses[0])
            rec["satisfied"], rec["item"] = True, None
            rec["matched_code"] = _norm(match.get("course_code", ""))
            satisfied_count += 1
    for course in courses[:satisfied_count]:
        leftovers.remove(course)   # its credits can't also count as elective


def _course_number(course: dict) -> int:
    m = re.search(r"\b(\d{1,3})", _norm(course.get("course_code", "")))
    return int(m.group(1)) if m else 0


def _assign_dept_level(records: list[dict], leftovers: list[dict]) -> None:
    """Satisfy department level-selection pool slots ("PLSC 400-Level") from
    leftover courses in that department at that level (400 covers 400-499),
    one course per slot in plan order."""
    for rec in records:
        slot = rec["slot"]
        if (rec["satisfied"] or slot.get("type") != "pool"
                or slot.get("ref") != "dept_level" or not slot.get("dept")):
            continue
        level = int(slot.get("level") or 0)
        hit = next(
            (c for c in leftovers
             if _dept(c) == slot["dept"] and level <= _course_number(c) < level + 100),
            None,
        )
        if hit:
            rec["satisfied"], rec["item"] = True, None
            rec["matched_code"] = _norm(hit.get("course_code", ""))
            leftovers.remove(hit)   # its credits can't also count as elective


def _assign_generic_gen_ed(records: list[dict], gen_ed_courses: list[str],
                           gen_ed_open: bool = True) -> None:
    """Satisfy the template's category-less generic gen-ed slots from the
    student's completed gen-ed courses, one course per slot in plan order.

    PSU bulletin plans list most of a degree's gen-ed credits as generic
    "General Education" cells with no specific category, so `match_template`'s
    category check can never satisfy them — leaving a student who has finished
    their gen-eds with a pile of phantom gen-ed slots re-scheduled into the
    future.  Each completed gen-ed course (from the gen-ed audit) stands in for
    one generic slot.  Courses already matched to a NAMED template slot are
    excluded by the caller so a course can't count twice."""
    pool = list(gen_ed_courses)
    for rec in records:
        slot = rec["slot"]
        if (rec["satisfied"] or slot.get("type") != "gen_ed"
                or slot.get("category")):
            continue
        if pool:
            code = pool.pop(0)
            rec["satisfied"], rec["item"] = True, None
            rec["matched_code"] = code
        elif not gen_ed_open:
            # No gen-ed domain is still open, so this slot is a leftover of the
            # template's credit accounting, not real work — and the picker would
            # open with nothing to choose.  Retire it.
            rec["satisfied"], rec["item"] = True, None


def _assign_electives(records: list[dict], leftovers: list[dict]) -> None:
    """Satisfy free-elective slots from the surplus-credit pool, in plan order.
    Purely credit-count based: any unclaimed course is by definition a free
    elective, whatever its dept."""
    pool = sum(_course_credits(c) for c in leftovers)
    for rec in records:
        if rec["satisfied"] or rec["slot"].get("type") != "elective":
            continue
        need = float(rec["slot"].get("credits", 3) or 3)
        if pool + 1e-9 >= need:
            pool -= need
            rec["satisfied"], rec["item"] = True, None
            rec["matched_code"] = f"{need:g} surplus credits"


def _assign_business_breadth(records: list[dict], leftovers: list[dict],
                             program_name: str | None) -> None:
    """Satisfy the Smeal Business Breadth requirement from leftover courses, using
    the sourced two-piece-sequence areas (see business_breadth.py).

    The two un-anchored `business_breadth` pool slots form ONE 6-cr two-piece
    sequence: they are filled from up to two leftover courses in a SINGLE area
    (the area the student has the most breadth courses in) — so a course from one
    area plus a course from another does NOT complete the sequence, matching
    Smeal's actual rule.  Any leftover breadth courses left over then satisfy
    "BA 411 or a Business Breadth course" slots (breadth pools carrying a BA 411
    anchor; the BA 411 half is already handled by the main anchor-code branch).

    Leftover-only (a course consumed by a required slot/audit is never miscounted)
    and consuming (its credits can't also fill a language/elective slot).
    Fail-safe: no qualifying leftover leaves the slots scheduled."""
    def _is_breadth(slot):
        return slot.get("type") == "pool" and slot.get("ref") == "business_breadth"

    pure = [r for r in records if not r["satisfied"] and _is_breadth(r["slot"])
            and "codes" not in r["slot"]]
    alt = [r for r in records if not r["satisfied"] and _is_breadth(r["slot"])
           and "codes" in r["slot"]]
    if not pure and not alt:
        return

    # Group leftover courses by the breadth area they belong to for this program.
    by_area: dict[str, list[dict]] = {}
    for c in leftovers:
        area = _bb.area_of(c.get("course_code", ""), program_name)
        if area:
            by_area.setdefault(area, []).append(c)

    # Two-piece sequence: take up to two courses from the student's MAJORITY area
    # (most courses, then alphabetical) so both slots come from one coherent area.
    if pure and by_area:
        area = sorted(by_area, key=lambda a: (-len(by_area[a]), a))[0]
        for rec, course in zip(pure, list(by_area[area])[:len(pure)]):
            rec["satisfied"], rec["item"] = True, None
            rec["matched_code"] = _norm(course.get("course_code", ""))
            leftovers.remove(course)
            by_area[area].remove(course)

    # "BA 411 or breadth" slots: any remaining leftover breadth course fills one.
    remaining = [c for cs in by_area.values() for c in cs]
    for rec in alt:
        if not remaining:
            break
        course = remaining.pop(0)
        rec["satisfied"], rec["item"] = True, None
        rec["matched_code"] = _norm(course.get("course_code", ""))
        leftovers.remove(course)


# ── Class-selector slot identity & options ───────────────────────────────────

def slot_identity(slot: dict, ordinal: int) -> tuple[str, str]:
    """(slot_kind, slot_key) — a stable requirement identity the class selector
    keys a student's course choice / semester pin on.  Code-based slots key on
    their course(s) so the key survives reflow; generic pool / elective /
    category-less gen-ed slots fold in a global slot `ordinal` (the slot's
    position in the template) to stay unique — two "General Education" or "Free
    elective" cells, even in the same semester, must not collapse to one key.
    The ordinal is stable because the template is fixed."""
    t = slot.get("type")
    if t == "course":
        return "course", f"course:{_base(slot.get('code', ''))}"
    if t == "choose_one":
        codes = sorted({_base(c) for c in slot.get("codes", []) if c})
        return "choose_one", "one:" + "|".join(codes)
    if t == "gen_ed":
        cat = slot.get("category")
        if cat:
            return "gen_ed", f"gened:{_norm(cat)}"
        return "gen_ed", f"gened:GENERAL#s{ordinal}"
    if t == "pool":
        codes = sorted({_base(c) for c in slot.get("codes", []) if c})
        if codes:
            return "pool", "pool:" + "|".join(codes)
        ref = _norm(str(slot.get("ref") or slot.get("label") or "pool"))
        return "pool", f"pool:{ref}#s{ordinal}"
    return "elective", f"elective:s{ordinal}"


def slot_options(slot: dict) -> list[dict]:
    """Bounded alternative courses the student can swap to for this slot, or []
    when the choice is unbounded (a whole gen-ed category or a large un-anchored
    pool — the catalog-browse case, out of scope for v1 swap)."""
    credits = float(slot.get("credits", 3) or 3)
    if slot.get("type") in ("choose_one", "pool"):
        codes = _dedupe_crosslisted(slot.get("codes", []))
        return [{"course_code": c, "course_title": "", "credits": credits} for c in codes]
    return []


# ── Match ────────────────────────────────────────────────────────────────────

def match_template(
    template: dict,
    taken: set[str],
    gen_ed_satisfied: dict[str, bool] | None = None,
    transcript_courses: list[dict] | None = None,
    used_codes: set[str] | None = None,
    gen_ed_courses: list[str] | None = None,
    course_choices: dict[str, str] | None = None,
    gen_ed_open: bool = True,
) -> list[dict]:
    """Walk the template in order and produce one record per slot:

        {sem_index, season, year, satisfied, matched_code, slot, item}

    `satisfied` slots are already done (transcript history); `item` is the
    schedulable dict for unsatisfied slots (None when satisfied).

    Satisfaction rules:
      * course / choose_one — satisfied if any option is in the taken set.
      * gen_ed with a named category (US/IL/GN/…) — satisfied if the gen-ed audit
        reports that category met.  A general (category-less) gen-ed slot is
        satisfied (when `gen_ed_courses` is passed) by one completed gen-ed
        course each, in plan order — so a student who has finished their gen-eds
        doesn't see those generic slots re-scheduled.
      * pool with anchor `codes` (e.g. an accounting elective anchored ACCTG 403W)
        — satisfied if an anchor is taken.
      * world-language pools, dept level-selection pools ("PLSC 400-Level"), and
        free electives (only when `transcript_courses` is passed) — satisfied
        from LEFTOVER courses: transcript courses neither a template slot nor an
        audit (`used_codes`, see build_used_codes) consumed.  Language slots take
        one leftover course from a `_WORLD_LANGUAGE_DEPTS` dept each; dept-level
        slots take one leftover course from their dept at their level; elective
        slots draw on the surplus credit pool.  Smeal "business breadth" pools
        take one leftover business-college course outside the major's own dept
        (see _assign_business_breadth).
    """
    gen_ed_satisfied = gen_ed_satisfied or {}
    consumed: set[str] = set()
    records: list[dict] = []

    for ordinal, (si, sem, slot) in enumerate(iter_slots(template)):
        t = slot.get("type")
        satisfied = False
        matched = None

        if t in ("course", "choose_one", "pool"):
            codes = [slot["code"]] if t == "course" else slot.get("codes", [])
            hit = _match_option(codes, taken, consumed) if codes else None
            if hit is not None:
                consumed.add(hit)
                satisfied, matched = True, hit
        elif t == "gen_ed":
            cat = slot.get("category")
            if cat and gen_ed_satisfied.get(_norm(cat)):
                satisfied, matched = True, cat
        # elective / un-anchored world_language: the leftover pass below

        item = None if satisfied else slot_to_item(slot)
        if item is not None:
            kind, skey = slot_identity(slot, ordinal)
            item["slot_key"] = skey
            item["slot_kind"] = kind
            if kind == "gen_ed" or (kind == "pool" and slot.get("ref") in ("world_language", "business_breadth") and not slot.get("codes")):
                # No bounded option list — the picker offers a course search instead
                # (gen-ed: pick a domain + course; world language: pick a language
                # course; business breadth: pick an area + its two-piece sequence).
                item["searchable"] = True
            opts = slot_options(slot)
            if opts:
                item["options"] = opts
            # Apply a stored course choice: schedule/display the chosen course
            # (a concrete course now fills a choose-one / anchored-pool slot).
            chosen = (course_choices or {}).get(skey)
            if chosen and (not opts or any(_codes_match(chosen, o["course_code"]) for o in opts)):
                item["chosen_code"] = chosen
                if kind != "course":
                    item["course_code"] = chosen
                    # Drop the placeholder ("Choose a … course" / the pair label) so
                    # _fill_future_titles backfills the chosen course's real catalog
                    # title instead of leaving the stale "choose" prompt on the card.
                    item["course_title"] = ""
                    if kind in ("pool", "gen_ed", "elective"):
                        item["is_pool"] = False

        records.append({
            "sem_index":   si,
            "season":      sem.get("term_season"),
            "year":        sem.get("year"),
            "satisfied":   satisfied,
            "matched_code": matched,
            "slot":        slot,
            "item":        item,
        })

    # Category-less generic gen-ed slots: satisfy from completed gen-ed courses.
    # Exclude only courses that are the LITERAL code of a named template slot —
    # those belong to that slot.  A course matched to a named slot merely via
    # equivalence (MATH 140 -> the template's MATH 110 slot) is NOT excluded: it's
    # a genuine extra gen-ed course still available for a generic slot, so a
    # student who has finished gen-eds isn't left with phantom gen-ed slots.
    if gen_ed_courses or not gen_ed_open:
        named_codes: set[str] = set()
        for r in records:
            s = r["slot"]
            if s.get("type") == "course":
                named_codes.add(_base(s.get("code", "")))
            elif s.get("type") in ("choose_one", "pool"):
                for c in s.get("codes", []):
                    named_codes.add(_base(c))
        pool = [c for c in (gen_ed_courses or []) if _base(c) not in named_codes]
        _assign_generic_gen_ed(records, pool, gen_ed_open)

    if transcript_courses:
        leftovers = _leftover_courses(transcript_courses, consumed, used_codes or set())
        _assign_world_language(records, leftovers)
        _assign_dept_level(records, leftovers)
        _assign_business_breadth(records, leftovers, template.get("program_name"))
        _assign_electives(records, leftovers)   # electives LAST — soaks up remainder

    return records
