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


def build_taken_set(transcript_courses: list[dict]) -> set[str]:
    """Base course codes the student has completed or is taking, expanded with
    known equivalences so a renamed/cross-listed course still matches a template."""
    taken: set[str] = set()
    for c in transcript_courses:
        if c.get("status") in ("done", "in_progress"):
            taken |= _equivalents(c.get("course_code", ""))
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


# ── Slot → schedulable timeline item ─────────────────────────────────────────

def _choose_one_label(codes: list[str]) -> str:
    # Mobile CourseRow splits on ' or ' for pair routing; keep it readable.
    return " or ".join(codes) if codes else ""


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
        return {"course_code": slot.get("label", "Requirement"),
                "course_title": f"Choose {int(credits)} credit(s)",
                "credits": credits, "is_pool": True,
                "pool_needed_credits": int(credits) if float(credits).is_integer() else credits,
                "pool_ref": slot.get("ref")}

    # elective
    return {"course_code": slot.get("label", "Elective"),
            "course_title": "Free elective", "credits": credits, "is_pool": True,
            "pool_needed_credits": int(credits) if float(credits).is_integer() else credits}


# ── Match ────────────────────────────────────────────────────────────────────

def match_template(
    template: dict,
    taken: set[str],
    gen_ed_satisfied: dict[str, bool] | None = None,
) -> list[dict]:
    """Walk the template in order and produce one record per slot:

        {sem_index, season, year, satisfied, matched_code, slot, item}

    `satisfied` slots are already done (transcript history); `item` is the
    schedulable dict for unsatisfied slots (None when satisfied).

    Satisfaction rules:
      * course / choose_one — satisfied if any option is in the taken set.
      * gen_ed with a named category (US/IL/GN/…) — satisfied if the gen-ed audit
        reports that category met.  A general (category-less) gen-ed slot is never
        pre-satisfied (there's no single course to point at).
      * pool with anchor `codes` (e.g. an accounting elective anchored ACCTG 403W)
        — satisfied if an anchor is taken.  Un-anchored pools (world language,
        business breadth) and electives are always scheduled — the transcript
        doesn't let us detect their completion cheaply (a known PoC limitation).
    """
    gen_ed_satisfied = gen_ed_satisfied or {}
    consumed: set[str] = set()
    records: list[dict] = []

    for si, sem, slot in iter_slots(template):
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
        # elective: never auto-satisfied

        records.append({
            "sem_index":   si,
            "season":      sem.get("term_season"),
            "year":        sem.get("year"),
            "satisfied":   satisfied,
            "matched_code": matched,
            "slot":        slot,
            "item":        None if satisfied else slot_to_item(slot),
        })

    return records
