"""
Corrections for credential pages the parser can't model on its own.

Each one was found by checking that a transcript which really completes the
credential reads as complete (see README, "Counting check"). They are applied
in `scrape_credentials.build()` after parsing, so a re-scrape keeps them; a page
whose shape changes makes its override fail loudly instead of applying blindly.

The rule for branching pages ("choose a track", "Option A or B", rules that
differ by student type): the branch becomes ONE adviser-confirmed requirement
carrying PSU's own wording, because the audit can't express "these courses OR
those courses" across whole requirement blocks, and guessing would tell a
student they'd finished when they hadn't.
"""

from __future__ import annotations

# Subject codes PSU's pages misspell. AGBM is the only agribusiness subject.
SUBJECT_TYPOS = {"ABGM": "AGBM", "AGMB": "AGBM"}


class OverrideMismatch(Exception):
    """The page no longer has the shape an override was written for."""


def _group(entry: dict, name: str, gtype: str | None = None) -> dict:
    hits = [g for g in entry["groups"]
            if g["name"] == name and (gtype is None or g["group_type"] == gtype)]
    if len(hits) != 1:
        raise OverrideMismatch(f"{entry['program_name']}: expected one group {name!r} "
                               f"({gtype}), found {len(hits)}")
    return hits[0]


def _adviser_block(name: str, section: str, credits: float, text: str,
                   min_grade: str = "C") -> dict:
    return {
        "name": name, "group_type": "unstructured_credits", "min_grade": min_grade,
        "section": section, "counts_toward_total": True,
        "threshold": credits, "threshold_max": None,
        "pool": {"text": text}, "courses": [], "section_credits": [None, None],
    }


def _dept_pool(name: str, section: str, credits: float, text: str, **spec) -> dict:
    return {
        "name": name, "group_type": "dept_credits", "min_grade": "C",
        "section": section, "counts_toward_total": True,
        "threshold": credits, "threshold_max": None,
        "pool": {"text": text, **spec}, "courses": [], "section_credits": [None, None],
    }


def _agribusiness(entry: dict) -> None:
    # "Select Option A or B: 9" -- A: one of five 300-level courses + 6 credits of
    # 400-level AGBM; B: 9 credits of 400-level AGBM (both excluding AGBM 496).
    # Exactly: 9 credits from {400-level AGBM} + those five, at least 6 at the 400
    # level. The page writes the subject as "ABGM" and "AGMB".
    old = [g for g in entry["groups"] if g["section"] == "Additional Courses"
           and g["group_type"] in ("unstructured_credits", "choose_courses", "dept_credits")]
    if len(old) != 4:
        raise OverrideMismatch(f"Agribusiness: expected 4 option groups, found {len(old)}")
    keep = [g for g in entry["groups"] if g not in old]
    keep.append(_dept_pool(
        "Additional Courses: Option A or B", "Additional Courses", 9,
        "Option A: one of AG 301, AGBM 302, AGBM 308W, AGBM 320, AGBM 338 and 6 credits "
        "of 400-level AGBM courses; or Option B: 9 credits of 400-level AGBM courses "
        "(AGBM 496 excluded unless approved by the AGBM program)",
        dept="AGBM", min_level=400, sub_level=400, sub_credits=6,
        include=["AG 301", "AGBM 302", "AGBM 308W", "AGBM 320", "AGBM 338"],
        exclude=["AGBM 496"]))
    entry["groups"] = keep


def _dispute_management(entry: dict) -> None:
    # "Select 12 credits of which 9 credits must be taken at the 400 level:" is the
    # header over three parts, not a pool of its own: LHR 437 or CAS 404, then
    # 6 credits from one list and 3 from another.
    head = _group(entry, "Additional Courses", "choose_credits")
    head.update(group_type="choose_one", threshold=None, counts_toward_total=True)
    for c in head["courses"]:
        c["pair_group_id"] = "dispute-437-404"
        c["credits"] = c.get("credits") or 3.0
    for name in ("Additional Courses: choose 6 credits", "Additional Courses: choose 3 credits"):
        _group(entry, name)["counts_toward_total"] = True


def _environmental_resource_management(entry: dict) -> None:
    # "Select 18 credits of the following: ABSM 327, SOILS 101, Any ERM course
    # (at least 6 credits must be at the 400-level)".
    g = _group(entry, "Additional Courses", "choose_credits")
    entry["groups"] = [_dept_pool(
        g["name"], g["section"], 18,
        "Select 18 credits from ABSM 327, SOILS 101, and any ERM course "
        "(at least 6 credits must be at the 400 level)",
        dept="ERM", sub_level=400, sub_credits=6, include=["ABSM 327", "SOILS 101"])]


def _east_european_studies(entry: dict) -> None:
    # "Select one of the following tracks: 11-16" -- four tracks of Russian,
    # Ukrainian and Polish language sequences.
    old = [g for g in entry["groups"] if g["section"] == "Additional Courses"]
    if len(old) != 4:
        raise OverrideMismatch(f"East European Studies: expected 4 track groups, found {len(old)}")
    keep = [g for g in entry["groups"] if g not in old]
    keep.insert(1, _adviser_block(
        "Additional Courses: language track", "Additional Courses", 11,
        "Select one track (11-16 credits). Track 1: RUS 3 or RUS 410, RUS 200, RUS 401. "
        "Track 2: UKR 3 and POL 1-3 or RUS 1-3. Track 3: POL 3 and UKR 1-3 or RUS 1-3. "
        "Track 4: RUS 3 or RUS 410 and POL 1-3 or UKR 1-3."))
    entry["groups"] = keep


def _geophysics(entry: dict) -> None:
    # Additional Courses (18-21) branch by student type; only "11-13 credits from
    # GEOSC 402Y-489" is common to both. The rest (GEOSC 203 + 3, or PHYS 212 +
    # 3-4 of MATH: 7 credits) is one adviser-confirmed block.
    sec = [g for g in entry["groups"] if g["section"] == "Additional Courses"]
    common = [g for g in sec if g["name"] == "Additional Courses: choose 11 credits"]
    if len(sec) != 5 or len(common) != 2:
        raise OverrideMismatch("Geophysics: Additional Courses changed shape")
    pool = dict(common[0], counts_toward_total=True, section_credits=[None, None])
    keep = [g for g in entry["groups"] if g not in sec]
    keep += [pool, _adviser_block(
        "Additional Courses: by student type", "Additional Courses", 7,
        "Non-Geoscience majors: GEOSC 203 and 3 credits from EARTH 2, EARTH 101, EARTH 105N, "
        "EARTH 106, GEOSC 1, GEOSC 10, GEOSC 40, GEOSC 109H. Geoscience majors: PHYS 212 "
        "and 3-4 credits from MATH 220, 230, 231, 232, 250, 251.")]
    entry["groups"] = keep


def _sustainability_leadership(entry: dict) -> None:
    # "Take the following 6 credits, or approved substitutions" is the header over
    # the two 3-credit pools below it, not a further 6 credits.
    head = _group(entry, "Additional Courses", "unstructured_credits")
    entry["groups"].remove(head)
    for g in entry["groups"]:
        if g["name"] == "Additional Courses: choose 3 credits":
            g["counts_toward_total"] = True


OVERRIDES = {
    "Agribusiness Management, Minor":           _agribusiness,
    "Dispute Management and Resolution, Minor": _dispute_management,
    "Environmental Resource Management, Minor": _environmental_resource_management,
    "East European Studies, Minor":             _east_european_studies,
    "Geophysics, Minor":                        _geophysics,
    "Sustainability Leadership, Minor":         _sustainability_leadership,
}


def apply(entry: dict) -> bool:
    """Correct `entry` in place. True when an override was applied."""
    for g in entry["groups"]:
        spec = g.get("pool") or {}
        for key in ("dept",):
            if spec.get(key) in SUBJECT_TYPOS:
                spec[key] = SUBJECT_TYPOS[spec[key]]
        if spec.get("depts"):
            spec["depts"] = [SUBJECT_TYPOS.get(d, d) for d in spec["depts"]]
    fix = OVERRIDES.get(entry["program_name"])
    if fix is None:
        return False
    fix(entry)
    return True
