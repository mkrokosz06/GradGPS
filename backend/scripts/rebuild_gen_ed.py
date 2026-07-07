"""
rebuild_gen_ed.py
-----------------
Rebuilds the __GEN_ED__ requirement pools in DynamoDB from AUTHORITATIVE data
scraped off the PSU bulletin (scripts/gen_ed_courses.json), replacing the
hand-authored (and partly fabricated) course lists in seed_gen_ed.py.

What it does:
  1. Clears all existing __GEN_ED__ rows.
  2. Writes the eight knowledge-domain / quantification / cultures pools
     (GQ, GA, GN, GH, GS, GHW, US, IL) straight from the scrape — real titles,
     real credits, real attribute designations, correct interdomain flags.
  3. Re-writes the three groups that are NOT plain attribute pools and are
     therefore still curated by hand in seed_gen_ed.py:
        - Communication: Effective Speech   (choose_one CAS 100A/B/C)
        - Communication: Writing            (choose_one ENGL 15 / ENGL 30)
        - GWS: Writing Across the Curriculum (W-suffix major courses)

Prereq: run scripts/scrape_gen_ed_courses.py first to produce gen_ed_courses.json.

Usage:
    python scripts/rebuild_gen_ed.py
"""

import sys, os, json
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import re
from boto3.dynamodb.conditions import Key
from db import requirements_table
from seed_gen_ed import GEN_ED_ROWS, PROGRAM


def _normalise_code(code: str) -> str:
    """Strip trailing W/H/N attribute suffixes exactly like the transcript
    parser (transcript_parser._normalise_code), so scraped codes match the
    normalised codes stored on student transcripts. Section letters (A/B/C)
    and other trailing letters (e.g. M) are preserved."""
    return re.sub(r"[WHN]$", "", code.strip())


def _normalise_courses(raw: dict) -> dict:
    """Collapse scraped codes to their transcript-normalised form, merging the
    gen-ed attributes of any suffixed variants (e.g. 'SOC 119N' → 'SOC 119')."""
    merged: dict = {}
    for code, c in raw.items():
        nc = _normalise_code(code)
        if nc in merged:
            m = merged[nc]
            m["attrs"] = sorted(set(m["attrs"]) | set(c.get("attrs", [])))
            # Prefer a real title over a "Foreign Studies"/placeholder one.
            if "Foreign Studies" in m.get("title", "") and "Foreign Studies" not in c.get("title", ""):
                m["title"] = c.get("title", m["title"])
        else:
            merged[nc] = {
                "title":   c.get("title", nc),
                "credits": c.get("credits", 3),
                "attrs":   sorted(set(c.get("attrs", []))),
            }
    for c in merged.values():
        c["multi_category"] = len(c["attrs"]) > 1
    return merged

# Domain / quantification / cultures pools rebuilt from the scrape.
DOMAIN_META = {
    "GQ":  ("GQ: Quantification",                 "choose_credits", 6),
    "GA":  ("GA: Arts",                           "choose_credits", 3),
    "GN":  ("GN: Natural Sciences",               "choose_credits", 6),
    "GH":  ("GH: Humanities",                     "choose_credits", 3),
    "GS":  ("GS: Social and Behavioral Sciences", "choose_credits", 3),
    "GHW": ("GHW: Health and Physical Activity",  "choose_credits", 3),
    "US":  ("US: United States Cultures",         "choose_credits", 3),
    "IL":  ("IL: International Cultures",          "choose_credits", 3),
}
DOMAIN_CODES = set(DOMAIN_META)

# Groups kept from the hand-curated seed (not derivable from a plain attribute
# pool). GWS foundation courses (ENGL 15, CAS 100) are covered by the two
# Communication groups, so scraped GWS designations are intentionally ignored.
# Writing Across the Curriculum is NOT a course list — it's a designation rule
# (3 credits of W/M/X/Y courses), written separately as a writing_intensive row.
FIXED_GROUPS = {
    "Communication: Effective Speech",
    "Communication: Writing",
}

# Writing Across the Curriculum: PSU requires 3 credits of writing-intensive
# (W/M/X/Y-suffixed) coursework within the major/college. Modelled as a single
# rule row, evaluated by audit_engine._eval_writing_intensive against the
# writing flag on transcript courses (and, in the timeline, planned W courses).
WAC_GROUP     = "Writing Across the Curriculum"
WAC_THRESHOLD = 3


def _clear_gen_ed():
    resp = requirements_table.query(KeyConditionExpression=Key("program_name").eq(PROGRAM))
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(PROGRAM),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items += resp.get("Items", [])
    with requirements_table.batch_writer() as batch:
        for it in items:
            batch.delete_item(Key={"program_name": it["program_name"],
                                   "group_course": it["group_course"]})
    print(f"  cleared {len(items)} existing __GEN_ED__ rows")


def _write_domains(courses: dict) -> tuple[int, dict]:
    from collections import Counter
    per_group = Counter()
    written = 0
    with requirements_table.batch_writer() as batch:
        for code, c in courses.items():
            kept = sorted(set(c.get("attrs", [])) & DOMAIN_CODES)
            if not kept:
                continue
            multi = len(kept) > 1
            for attr in kept:
                group_name, gtype, threshold = DOMAIN_META[attr]
                item = {
                    "program_name":      PROGRAM,
                    "group_course":      f"{group_name}#{code}",
                    "requirement_group": group_name,
                    "group_type":        gtype,
                    "group_threshold":   Decimal(str(threshold)),
                    "course_code":       code,
                    "course_title":      c.get("title", code),
                    "credits":           Decimal(str(c.get("credits", 3))),
                    "min_grade":         "D",
                }
                if multi:
                    item["multi_category"] = True
                batch.put_item(Item=item)
                per_group[group_name] += 1
                written += 1
    return written, dict(per_group)


def _write_fixed_groups() -> int:
    written = 0
    with requirements_table.batch_writer() as batch:
        for i, row in enumerate(GEN_ED_ROWS):
            (group, gtype, threshold, code, title, credits,
             min_grade, pair_id, multi_cat) = row
            if group not in FIXED_GROUPS:
                continue
            item = {
                "program_name":      PROGRAM,
                "group_course":      f"{group}#{code}#{i}",
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
            written += 1
    return written


def _write_wac():
    """Write the single Writing Across the Curriculum rule row."""
    requirements_table.put_item(Item={
        "program_name":      PROGRAM,
        "group_course":      f"{WAC_GROUP}#WAC",
        "requirement_group": WAC_GROUP,
        "group_type":        "writing_intensive",
        "group_threshold":   Decimal(str(WAC_THRESHOLD)),
        "course_code":       "W",
        "course_title":      "Writing-intensive (W) course",
        "credits":           Decimal(str(WAC_THRESHOLD)),
        "min_grade":         "D",
    })


def rebuild():
    json_path = Path(__file__).parent / "gen_ed_courses.json"
    if not json_path.exists():
        sys.exit("gen_ed_courses.json not found — run scrape_gen_ed_courses.py first.")
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    courses = _normalise_courses(raw)
    print(f"Loaded {len(raw)} scraped courses -> {len(courses)} after code normalisation.")

    print("Clearing existing gen-ed rows...")
    _clear_gen_ed()

    print("Writing domain pools from scrape...")
    n_dom, per_group = _write_domains(courses)
    for g in sorted(per_group):
        print(f"    {per_group[g]:4d}  {g}")

    print("Writing hand-curated fixed groups...")
    n_fixed = _write_fixed_groups()

    print("Writing Writing-Across-the-Curriculum rule...")
    _write_wac()

    print(f"\nDone. {n_dom} domain-pool rows + {n_fixed} fixed-group rows "
          f"+ 1 WAC rule = {n_dom + n_fixed + 1} total.")


if __name__ == "__main__":
    rebuild()
