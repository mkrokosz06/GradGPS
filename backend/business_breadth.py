"""Smeal Business Breadth — the sourced two-piece-sequence areas.

Business Breadth = complete ONE two-piece sequence (6 cr) from a single thematic
area, outside the student's own major. The authoritative list isn't in the PSU
bulletin (it points to the Smeal website), so it's hand-sourced into
`scripts/business_breadth_courses.json` (see scripts/build_business_breadth.py).

Pure and DB-free: the timeline/matcher and the /courses/for-slot picker call in
to learn which areas/courses a given program's breadth requirement offers, with
the student's own major area excluded (union + exclusion). Only some majors have
been sourced, so `disclaimer()` ships alongside every surfaced list.
"""
import functools
import json
import os
import re

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "scripts", "business_breadth_courses.json")


@functools.lru_cache(maxsize=1)
def _doc() -> dict:
    try:
        with open(_DATA, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"areas": {}, "exclude_area_by_program": {}, "disclaimer": ""}


def _base(code: str) -> str:
    """'MKTG 445W' -> 'MKTG 445' (strip one trailing attribute letter)."""
    c = re.sub(r"\s+", " ", (code or "").strip().upper())
    m = re.match(r"^([A-Z]+ \d+)[WHNMXYRSU]$", c)
    return m.group(1) if m else c


def disclaimer() -> str:
    return _doc().get("disclaimer", "")


def excluded_area(program_name: str | None) -> str | None:
    """The area a program excludes (its own major), or None."""
    return (_doc().get("exclude_area_by_program") or {}).get(program_name or "")


def areas_for_program(program_name: str | None) -> dict[str, dict]:
    """Ordered {area: spec} available to this program — every sourced area except
    the student's own major area. `spec` is {pick, courses:[{code,title,...}],
    structure?}."""
    excl = excluded_area(program_name)
    return {a: spec for a, spec in _doc().get("areas", {}).items() if a != excl}


def area_names(program_name: str | None) -> list[str]:
    """Area labels for the picker's chips (own major area removed)."""
    return list(areas_for_program(program_name).keys())


def area_courses(area: str) -> list[dict]:
    return list((_doc().get("areas", {}).get(area) or {}).get("courses", []))


def all_courses(program_name: str | None) -> list[dict]:
    """Every distinct breadth course available to this program, each tagged with
    its `area` — the picker's search corpus and the matcher's universe."""
    seen: set[str] = set()
    out: list[dict] = []
    for area, spec in areas_for_program(program_name).items():
        for c in spec.get("courses", []):
            b = _base(c.get("code", ""))
            if b and b not in seen:
                seen.add(b)
                out.append({**c, "area": area})
    return out


def area_of(code: str, program_name: str | None) -> str | None:
    """Which available area a course belongs to (base-code match), or None if the
    course isn't a breadth course for this program."""
    b = _base(code)
    for area, spec in areas_for_program(program_name).items():
        for c in spec.get("courses", []):
            if _base(c.get("code", "")) == b:
                return area
    return None
