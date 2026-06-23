"""
Seeds PSU's General Education requirements into the requirements table
under the reserved program_name "__GEN_ED__".

These are university-wide graduation requirements, not major-specific.
Uses pool-based (choose_credits) groups for attribute categories and
required-exact rows for the two mandatory first-year courses.

Interdomain / dual-designated courses
--------------------------------------
Some PSU courses carry TWO gen ed attribute codes (e.g. "GH; US" or "GN; GA").
These are listed in BOTH of their respective pools and flagged multi_category=True.
The audit engine exempts multi_category courses from the consumed set, so a single
course can satisfy two categories simultaneously — which is exactly what PSU allows.

Usage:
    python scripts/seed_gen_ed.py

Safe to re-run — uses PutItem upserts.
"""

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

from db import requirements_table

PROGRAM = "__GEN_ED__"

# ── Gen Ed requirement definitions ──────────────────────────────────────────
# Tuple fields:
#   (requirement_group, group_type, group_threshold,
#    course_code, course_title, credits, min_grade,
#    pair_group_id, multi_category)
#
# multi_category=True  → course carries 2 PSU gen ed attributes.
#                         It is listed in both pools and exempt from the
#                         course-consumption rule (satisfies both groups).
# multi_category=False → normal single-category course (most rows).

GEN_ED_ROWS = [

    # ── Communication: Effective Speech (choose one section) ─────────────────
    ("Communication: Effective Speech", "choose_one", None,
     "CAS 100A", "Effective Speech", 3, "D", 1, False),
    ("Communication: Effective Speech", "choose_one", None,
     "CAS 100B", "Effective Speech", 3, "D", 1, False),
    ("Communication: Effective Speech", "choose_one", None,
     "CAS 100C", "Effective Speech", 3, "D", 1, False),

    # ── Communication: Writing (ENGL 15 or ENGL 30H) ─────────────────────────
    ("Communication: Writing", "choose_one", None,
     "ENGL 15",  "Rhetoric and Composition", 3, "D", 2, False),
    ("Communication: Writing", "choose_one", None,
     "ENGL 30H", "Rhetoric and Composition — Honors", 3, "D", 2, False),

    # ── GQ — Quantification (6 credits min) ──────────────────────────────────
    ("GQ: Quantification", "choose_credits", 6,
     "MATH 22",  "College Algebra II", 3, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "MATH 26",  "Plane Trigonometry", 3, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "MATH 110", "Techniques of Calculus I", 4, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "MATH 140", "Calculus with Analytic Geometry I", 4, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "MATH 141", "Calculus with Analytic Geometry II", 4, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "MATH 220", "Matrices", 2, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "MATH 230", "Calculus and Vector Analysis", 4, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "STAT 200", "Elementary Statistics", 4, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "STAT 318", "Statistics for Social Sciences", 3, "D", None, False),
    ("GQ: Quantification", "choose_credits", 6,
     "STAT 415", "Introduction to Mathematical Statistics I", 3, "D", None, False),

    # ── GN — Natural Sciences (6 credits min) ────────────────────────────────
    ("GN: Natural Sciences", "choose_credits", 6,
     "BIOL 110", "Basic Concepts in Biology", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "BIOL 127", "Biology of Nutrition", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "BIOL 240", "Microbiology", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "CHEM 110", "Chemical Principles I", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "CHEM 112", "Chemical Principles II", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "GEOG 10",  "Physical Geography", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "GEOG 120", "Environment and Society", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "METEO 101","Weather and Climate", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "PHYS 211", "General Physics: Mechanics", 4, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "PHYS 212", "General Physics: Electricity and Magnetism", 4, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "PHYS 213", "General Physics: Modern Physics", 2, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "PHYS 250", "Introductory Physics I", 3, "D", None, False),
    ("GN: Natural Sciences", "choose_credits", 6,
     "EARTH 101","Earth and Environment", 3, "D", None, False),
    # Interdomain GN;GS — satisfies both Natural Sciences AND Social Sciences
    ("GN: Natural Sciences", "choose_credits", 6,
     "GEOG 001", "Human Geography", 3, "D", None, True),   # GN;GS dual

    # ── GA — Arts (3 credits min) ─────────────────────────────────────────────
    ("GA: Arts", "choose_credits", 3,
     "ART 101",  "Introductory Drawing", 3, "D", None, False),
    ("GA: Arts", "choose_credits", 3,
     "ART 201",  "Two-Dimensional Design", 3, "D", None, False),
    ("GA: Arts", "choose_credits", 3,
     "MUSC 007", "Understanding Music", 3, "D", None, False),
    ("GA: Arts", "choose_credits", 3,
     "THEA 100", "Introduction to Theatre", 3, "D", None, False),
    ("GA: Arts", "choose_credits", 3,
     "FILM 100", "Introduction to Film", 3, "D", None, False),
    ("GA: Arts", "choose_credits", 3,
     "DART 100", "Digital Arts", 3, "D", None, False),
    # Interdomain GA;GH — satisfies both Arts AND Humanities
    ("GA: Arts", "choose_credits", 3,
     "ENGL 202A","Creative Writing: Fiction", 3, "D", None, True),   # GA;GH dual

    # ── GH — Humanities (3 credits min) ──────────────────────────────────────
    ("GH: Humanities", "choose_credits", 3,
     "HIST 020", "History of Western Civilization I", 3, "D", None, False),
    ("GH: Humanities", "choose_credits", 3,
     "HIST 021", "History of Western Civilization II", 3, "D", None, False),
    ("GH: Humanities", "choose_credits", 3,
     "PHIL 001", "Reasoning and Critical Thinking", 3, "D", None, False),
    ("GH: Humanities", "choose_credits", 3,
     "PHIL 010", "Introduction to Philosophy", 3, "D", None, False),
    ("GH: Humanities", "choose_credits", 3,
     "ENGL 050", "Introduction to Literature", 3, "D", None, False),
    ("GH: Humanities", "choose_credits", 3,
     "ENGL 202D","Technical Writing", 3, "D", None, False),
    ("GH: Humanities", "choose_credits", 3,
     "RELI 001", "Introduction to Religious Studies", 3, "D", None, False),
    # Interdomain GH;US — satisfies both Humanities AND US Cultures
    ("GH: Humanities", "choose_credits", 3,
     "HIST 110", "American Civilization", 3, "D", None, True),       # GH;US dual
    ("GH: Humanities", "choose_credits", 3,
     "ENGL 202A","Creative Writing: Fiction", 3, "D", None, True),   # GA;GH dual
    # Interdomain GH;IL — satisfies both Humanities AND International Cultures
    ("GH: Humanities", "choose_credits", 3,
     "ANTH 001", "Introduction to Anthropology", 3, "D", None, True), # GH;IL dual

    # ── GS — Social and Behavioral Sciences (3 credits min) ──────────────────
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "ECON 102", "Introductory Microeconomic Analysis", 3, "D", None, False),
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "ECON 104", "Introductory Macroeconomic Analysis", 3, "D", None, False),
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "PSYCH 100","Introductory Psychology", 3, "D", None, False),
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "SOC 001",  "Introductory Sociology", 3, "D", None, False),
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "SOC 119",  "Social Dimensions of Information and Communication Technology", 3, "D", None, False),
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "CRIMJ 100","Introduction to Criminal Justice", 3, "D", None, False),
    # Interdomain GN;GS — satisfies both Natural Sciences AND Social Sciences
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "GEOG 001", "Human Geography", 3, "D", None, True),   # GN;GS dual
    # Interdomain GS;US — satisfies both Social Sciences AND US Cultures
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "PLSC 001", "American Politics", 3, "D", None, True),  # GS;US dual
    # Interdomain GS;IL — satisfies both Social Sciences AND International Cultures
    ("GS: Social and Behavioral Sciences", "choose_credits", 3,
     "GEOG 128", "World Regional Geography", 3, "D", None, True),  # GS;IL dual

    # ── GHW — Health and Physical Activity (3 credits min) ───────────────────
    ("GHW: Health and Physical Activity", "choose_credits", 3,
     "HPA 100",  "Personal Health and Wellness", 3, "D", None, False),
    ("GHW: Health and Physical Activity", "choose_credits", 3,
     "KINES 1",  "Introduction to Kinesiology", 3, "D", None, False),
    ("GHW: Health and Physical Activity", "choose_credits", 3,
     "KINES 3",  "Physical Fitness and Wellness", 1, "D", None, False),
    ("GHW: Health and Physical Activity", "choose_credits", 3,
     "NURS 200", "Health and Wellness", 3, "D", None, False),
    # BIOL 127 omitted here — it is a single-category GN course only.

    # ── US Cultures (3 credits min) ───────────────────────────────────────────
    # Courses with the US attribute. Many also carry a domain code (GH or GS),
    # so they are flagged multi_category=True and listed in both pools.
    ("US: United States Cultures", "choose_credits", 3,
     "HIST 110", "American Civilization", 3, "D", None, True),      # GH;US dual
    ("US: United States Cultures", "choose_credits", 3,
     "PLSC 001", "American Politics", 3, "D", None, True),          # GS;US dual
    ("US: United States Cultures", "choose_credits", 3,
     "SOC 001",  "Introductory Sociology", 3, "D", None, True),     # GS;US dual
    ("US: United States Cultures", "choose_credits", 3,
     "CRIMJ 100","Introduction to Criminal Justice", 3, "D", None, True), # GS;US dual
    ("US: United States Cultures", "choose_credits", 3,
     "AFAM 100", "Introduction to African American Studies", 3, "D", None, True),
    ("US: United States Cultures", "choose_credits", 3,
     "WMST 100", "Introduction to Women's Studies", 3, "D", None, True),

    # ── IL — International/Intercultural Competence (3 credits min) ──────────
    # Courses with the IL attribute. Many also carry a domain code (GH or GS).
    ("IL: International Cultures", "choose_credits", 3,
     "ANTH 001", "Introduction to Anthropology", 3, "D", None, True),  # GH;IL dual
    ("IL: International Cultures", "choose_credits", 3,
     "GEOG 128", "World Regional Geography", 3, "D", None, True),      # GS;IL dual
    ("IL: International Cultures", "choose_credits", 3,
     "GEOG 001", "Human Geography", 3, "D", None, True),               # GN;GS (also IL at some campuses)
    ("IL: International Cultures", "choose_credits", 3,
     "HIST 020", "History of Western Civilization I", 3, "D", None, True),  # GH;IL dual
    ("IL: International Cultures", "choose_credits", 3,
     "HIST 021", "History of Western Civilization II", 3, "D", None, True), # GH;IL dual
    ("IL: International Cultures", "choose_credits", 3,
     "RELI 001", "Introduction to Religious Studies", 3, "D", None, True),  # GH;IL dual
    ("IL: International Cultures", "choose_credits", 3,
     "SPAN 1",   "Elementary Spanish I", 3, "D", None, False),
    ("IL: International Cultures", "choose_credits", 3,
     "SPAN 2",   "Elementary Spanish II", 3, "D", None, False),
    ("IL: International Cultures", "choose_credits", 3,
     "FR 1",     "Elementary French I", 3, "D", None, False),
    ("IL: International Cultures", "choose_credits", 3,
     "FR 2",     "Elementary French II", 3, "D", None, False),

    # ── GWS — Writing Across the Curriculum (3 W-designated courses min) ─────
    # W courses are discipline-specific. List the most common for IST/ETI students.
    # W courses can also carry domain or US/IL attributes — flagged accordingly.
    ("GWS: Writing Across the Curriculum", "choose_courses", 3,
     "IST 302",  "Information and Organizations", 3, "D", None, False),
    ("GWS: Writing Across the Curriculum", "choose_courses", 3,
     "IST 331",  "Information and Persuasion", 3, "D", None, False),
    ("GWS: Writing Across the Curriculum", "choose_courses", 3,
     "IST 356",  "Contemporary Issues in IST", 3, "D", None, False),
    ("GWS: Writing Across the Curriculum", "choose_courses", 3,
     "IST 432",  "Strategic Leadership of Technology", 3, "D", None, False),
    ("GWS: Writing Across the Curriculum", "choose_courses", 3,
     "IST 440",  "IST Integration and Problem Solving", 3, "D", None, False),
    ("GWS: Writing Across the Curriculum", "choose_courses", 3,
     "SRA 111",  "Security Risk Analysis", 3, "D", None, False),
    ("GWS: Writing Across the Curriculum", "choose_courses", 3,
     "ENGL 202D","Technical Writing", 3, "D", None, False),
]


def seed_gen_ed():
    print(f"Seeding gen ed requirements under program_name='{PROGRAM}'...")
    count = 0
    with requirements_table.batch_writer() as batch:
        for i, row in enumerate(GEN_ED_ROWS):
            (group, gtype, threshold, code, title, credits,
             min_grade, pair_id, multi_cat) = row

            group_course = f"{group}#{code}#{i}"

            item = {
                "program_name":      PROGRAM,
                "group_course":      group_course,
                "requirement_group": group,
                "group_type":        gtype,
                "course_code":       code,
                "course_title":      title,
                "credits":           Decimal(str(credits)),
                "min_grade":         min_grade,
            }

            if threshold is not None:
                item["group_threshold"] = Decimal(str(threshold))

            if pair_id is not None:
                item["pair_group_id"] = Decimal(str(pair_id))

            if multi_cat:
                item["multi_category"] = True

            batch.put_item(Item=item)
            count += 1

    print(f"  {count} gen ed rows written.")
    multi = sum(1 for r in GEN_ED_ROWS if r[8])
    print(f"  {multi} rows flagged multi_category (interdomain / dual-designated).")


if __name__ == "__main__":
    seed_gen_ed()
    print("\nGen Ed seeding complete.")
