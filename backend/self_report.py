"""
No-transcript mode: a student enters the classes they've taken instead of
uploading a PDF. Pure helpers (no DB), used by routers/transcript.py.

The walkthrough reuses the major's Suggested Academic Plan as a checklist: most
students roughly follow it, so correcting a pre-filled list is far easier than
recalling every class from memory. Majors without a template get suggestions
from their requirement rows instead.

Grades are a single "C or better?" answer, not per-course grades. A course the
student marks "below a C" is stored with grade "D", so any requirement with a
C minimum treats it as not met; everything else is stored with no grade, which
`audit_engine._grade_meets` already reads as meeting the requirement.
"""

from datetime import date

from plan_templates import iter_slots
from sap_schedule import _base

SELF_REPORTED = "self_reported"
BELOW_C_GRADE = "D"
MAX_COURSES = 120          # a whole degree is ~40-45 courses; generous cap
MAX_POOL_OPTIONS = 40      # a bigger list isn't a list a student scrolls; search instead

_GEN_ED_LABELS = {
    "GA": "Arts (GA)", "GH": "Humanities (GH)", "GN": "Natural Sciences (GN)",
    "GS": "Social Sciences (GS)", "GQ": "Quantification (GQ)",
    "GHW": "Health & Wellness (GHW)", "US": "US Cultures (US)",
    "IL": "International Cultures (IL)", "GWS": "Writing/Speaking (GWS)",
}


def current_term(today: date | None = None) -> str:
    """The term a student is 'in' right now. Summer counts toward the coming fall:
    someone setting up in July is planning around their fall schedule."""
    d = today or date.today()
    if d.month <= 5:
        return f"SP {d.year}"
    return f"FA {d.year}"


def previous_terms(term: str, n: int) -> list[str]:
    """The n Fall/Spring terms before `term`, oldest first."""
    season, year = term.split()
    year = int(year)
    out = []
    for _ in range(n):
        if season == "FA":
            season = "SP"
        else:
            season, year = "FA", year - 1
        out.append(f"{season} {year}")
    return list(reversed(out))


def _course(code: str, bulletin: dict, credits=None) -> dict:
    info = bulletin.get(code) or {}
    return {
        "code":    code,
        "title":   info.get("title", ""),
        "credits": float(info.get("credits") or credits or 3),
    }


def _fits(code: str, dept: str | None, level: int | None) -> bool:
    subj, _, num = code.partition(" ")
    if dept and subj != dept:
        return False
    digits = "".join(ch for ch in num if ch.isdigit())
    return not level or (digits != "" and level <= int(digits) < level + 100)


def pool_options(rows: list[dict], template: dict) -> dict[str, list[str]]:
    """The course lists a plan's placeholder slots stand for, from the major's own
    requirement rows (already narrowed to the student's option and focus).

    - "focus": every Application Focus pool row (the student's area, or the
      any-area pool before they pick one).
    - "major": the other credit pools the template doesn't itemize. A pool any of
      whose courses is a named plan slot belongs to that slot (ETI's intro
      programming pool is the IST 140 slot); the rest are what a "Pick from the
      Business Fundamentals list" cell means. Same rule as
      sap_schedule.build_major_pool_codes, which retires those slots."""
    named: set[str] = set()
    for _, _, slot in iter_slots(template):
        if slot.get("type") == "course":
            named.add(_base(slot.get("code", "")))
        elif slot.get("type") in ("choose_one", "pool"):
            named |= {_base(c) for c in slot.get("codes", [])}

    pools: dict[tuple, list[str]] = {}
    for r in rows:
        if r.get("group_type") != "choose_credits":
            continue
        key = (r.get("requirement_group"), str(r.get("group_threshold")),
               str(r.get("pool_seq")), r.get("focus_area") or "")
        code = (r.get("course_code") or "").strip().upper()
        if code:
            pools.setdefault(key, []).append(code)

    focus: list[str] = []
    major: list[str] = []
    for key, codes in pools.items():
        if key[3]:
            focus += codes
        elif not {_base(c) for c in codes} & named:
            major += codes
    dedupe = lambda xs: list(dict.fromkeys(xs))
    return {"focus": dedupe(focus), "major": dedupe(major)}


def _slot_options(slot: dict, pools: dict[str, list[str]]) -> list[str]:
    ref = slot.get("ref")
    if ref == "application_focus":
        codes = pools.get("focus", [])
    elif ref == "major_selection":
        codes = [c for c in pools.get("major", [])
                 if _fits(c, slot.get("dept"), slot.get("level"))]
    else:
        return []
    return codes if len(codes) <= MAX_POOL_OPTIONS else []


def _slot_item(slot: dict, bulletin: dict, pools: dict | None = None) -> dict | None:
    t = slot.get("type")
    credits = float(slot.get("credits") or 3)
    if t == "course":
        return {"kind": "course", **_course(slot["code"], bulletin, credits)}
    if t == "choose_one":
        return {"kind": "choice", "credits": credits,
                "options": [_course(c, bulletin, credits) for c in slot.get("codes", [])]}
    if t == "gen_ed":
        cat = slot.get("category")
        label = f"Gen Ed: {_GEN_ED_LABELS.get(cat, cat)}" if cat else "Gen Ed course"
        return {"kind": "open", "label": label, "credits": credits, "gen_ed": cat}
    if t in ("pool", "elective"):
        item = {"kind": "open", "label": slot.get("label") or "Elective", "credits": credits}
        if slot.get("dept"):
            item["dept"] = slot["dept"]
        codes = slot.get("codes") or _slot_options(slot, pools or {})
        if codes:
            item["suggested"] = [_course(c, bulletin, credits) for c in codes]
            # A list the slot stands for (not just a hint): a class from it entered
            # on an earlier card already fills this slot.
            item["fills_from"] = not slot.get("codes")
        return item
    return None


def plan_semesters(template: dict, bulletin: dict, pools: dict | None = None) -> list[dict]:
    """The template's Fall/Spring semesters as walkthrough cards, in plan order.
    Summer terms are left out; a summer course is rare enough to add by hand."""
    sems: list[dict] = []
    index: dict[int, dict] = {}
    for si, sem, slot in iter_slots(template):
        if sem.get("term_season") not in ("FA", "SP"):
            continue
        if si not in index:
            index[si] = {"year": sem.get("year"), "season": sem.get("term_season"), "items": []}
            sems.append(index[si])
        item = _slot_item(slot, bulletin, pools)
        if item:
            index[si]["items"].append(item)
    return sems


def suggestions_from_rows(rows: list[dict], bulletin: dict, limit: int = 60) -> list[dict]:
    """For a major with no plan template: the courses its requirements name
    outright (required + choose-one alternatives), as quick-add chips."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r.get("group_type", "required") not in ("required", "choose_one"):
            continue
        code = (r.get("course_code") or "").strip().upper()
        if not code or code in seen or code not in bulletin:
            continue
        seen.add(code)
        out.append(_course(code, bulletin, r.get("credits")))
        if len(out) >= limit:
            break
    return out
