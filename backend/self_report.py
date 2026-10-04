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

SELF_REPORTED = "self_reported"
BELOW_C_GRADE = "D"
MAX_COURSES = 120          # a whole degree is ~40-45 courses; generous cap

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


def _slot_item(slot: dict, bulletin: dict) -> dict | None:
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
        if slot.get("codes"):
            item["suggested"] = [_course(c, bulletin, credits) for c in slot["codes"]]
        return item
    return None


def plan_semesters(template: dict, bulletin: dict) -> list[dict]:
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
        item = _slot_item(slot, bulletin)
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
