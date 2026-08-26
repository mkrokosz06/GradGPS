"""Build data/business_breadth_courses.json — the union master list of Smeal
"Business Breadth" two-piece-sequence areas.

Business Breadth = complete ONE two-piece sequence (6 credits) from a single
thematic area, at least 3 credits at the 400 level. PSU's bulletin doesn't
enumerate the courses (it points to the Smeal website), so this list is
hand-sourced from the Smeal degree-requirement pages and unioned across majors.
Per student, EXCLUDE the area matching their own major (exclude_area_by_program).

Sourced so far: Accounting (grouped) + Finance (flat). Add the other 7 majors by
extending AREAS / EXCLUDE_AREA_BY_PROGRAM and re-running. Every code is validated
against scripts/bulletin_course_titles.json; real courses missing from that
snapshot are titled via MANUAL_TITLES and flagged in_catalog=false.

    python scripts/build_business_breadth.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BK = os.path.dirname(HERE)
titles = json.load(open(os.path.join(HERE, "bulletin_course_titles.json"), encoding="utf-8"))

# Union of areas across the sourced major pages. Where pages disagreed on how many
# courses an area offers, take the broader union.
AREAS = {
    "Accounting":                               ["ACCTG 404", "ACCTG 471", "ACCTG 472"],
    "Business Law":                             ["BLAW 424", "BLAW 425", "BLAW 441", "BLAW 444", "BLAW 445", "BLAW 446", "BLAW 447", "BLAW 499"],
    "Business Sustainability":                  ["BA 441", "BA 442", "SCM 448"],
    "Corporate Diversity":                      ["MGMT 320", "MGMT 445"],
    "Corporate Innovation and Entrepreneurship":["MGMT 425", "MGMT 453"],
    "Finance":                                  ["FIN 305", "FIN 406", "FIN 408"],
    "Information Systems Management":            ["MIS 301", "MIS 431", "MIS 437", "MIS 441", "MIS 446"],
    "International Business":                    ["IB 303", "IB 403", "IB 404", "IB 450", "IB 460", "IB 470", "IB 497"],
    "Management":                               ["MGMT 326", "MGMT 410", "MGMT 420", "MGMT 481"],
    "Marketing":                                ["MKTG 327", "MKTG 330", "MKTG 422", "MKTG 445"],
    "Real Estate":                              ["RM 303", "RM 450"],
    "Risk Management":                          ["RM 302", "RM 440", "RM 475"],
    "Supply Chain and Information Systems":      ["SCM 404", "SCM 405", "SCM 406", "SCM 421", "SCM 448"],
}
# Areas that aren't a plain "pick 2 from this list".
SPECIAL = {
    "Economics": "Complete 3 cr of 300/400-level ECON + 3 cr of 400-level ECON.",
    "Marketing": "Complete one of {MKTG 327, MKTG 330} AND one of {MKTG 422, MKTG 445}.",
}
# The area each Smeal major excludes (its own), keyed by GradGPS program_name.
EXCLUDE_AREA_BY_PROGRAM = {
    "Accounting, B.S. (Business)": "Accounting",
    "Finance, B.S. (Business)": "Finance",
    "Marketing, B.S. (Business)": "Marketing",
    "Management, B.S. (Business)": "Management",
    "Supply Chain and Information Systems, B.S.": "Supply Chain and Information Systems",
    "Business Analytics and Information Systems, B.S.": "Information Systems Management",
    "Real Estate, B.S.": "Real Estate",
    "Risk Management, B.S.": "Risk Management",
    "Corporate Innovation and Entrepreneurship, B.S.": "Corporate Innovation and Entrepreneurship",
}
# Real courses (authoritative Smeal source) absent from our catalog snapshot.
MANUAL_TITLES = {"BLAW 425": "Business and Environmental Regulation"}


def _is_400(code: str) -> bool:
    parts = code.split()
    return len(parts) == 2 and parts[1][:1].isdigit() and int(parts[1][:1]) >= 4


def main():
    missing = []
    areas_out = {}
    for area, codes in AREAS.items():
        courses = []
        for c in codes:
            t = titles.get(c)
            in_catalog = t is not None
            if not in_catalog:
                missing.append((area, c))
                t = MANUAL_TITLES.get(c, "")
            entry = {"code": c, "title": t, "level_400": _is_400(c)}
            if not in_catalog:
                entry["in_catalog"] = False
            courses.append(entry)
        e = {"pick": 2, "courses": courses}
        if area in SPECIAL:
            e["structure"] = SPECIAL[area]
        areas_out[area] = e
    areas_out["Economics"] = {"pick": 2, "courses": [], "structure": SPECIAL["Economics"]}

    doc = {
        "requirement": "Complete ONE two-piece sequence (6 credits) from a single area; at least 3 credits must be at the 400 level overall.",
        "coverage": "Union of the sourced Smeal major lists. Per student, EXCLUDE the area matching their own major (exclude_area_by_program). Only 2 of 9 major lists sourced so far.",
        "disclaimer": "Please double-check with your adviser — we may not have every approved Business Breadth course.",
        "sources": [
            "ugstudents.smeal.psu.edu/.../majors/accounting-degree-requirements (grouped two-piece sequences)",
            "ugstudents.smeal.psu.edu/.../majors/finance-degree-requirements (flat list)",
        ],
        "as_of": "2026-08",
        "exclude_area_by_program": EXCLUDE_AREA_BY_PROGRAM,
        "areas": areas_out,
    }

    out = os.path.join(HERE, "business_breadth_courses.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = sum(len(a["courses"]) for a in areas_out.values())
    print(f"Wrote {out}")
    print(f"Areas: {len(areas_out)} | distinct course entries: {total}")
    print(f"Not in our catalog snapshot (flagged): {[c for _, c in missing]}"
          if missing else "All codes validated against the catalog title map.")


if __name__ == "__main__":
    main()
