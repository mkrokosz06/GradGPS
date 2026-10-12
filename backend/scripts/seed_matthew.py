"""
Seeds Matthew Krokosz's user record and transcript into DynamoDB.
Then runs a live audit via the audit engine.

Usage:
    python scripts/seed_matthew.py [path/to/transcript.pdf]

If no PDF path given, uses pre-populated test data.
"""

import sys, os, json
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

from db import users_table, transcript_table, requirements_table
from boto3.dynamodb.conditions import Key

USER_ID = "matthew-test-001"
MAJOR   = "Enterprise Technology Integration, B.S. (Information Sciences and Technology)"

def seed_user():
    print(f"Seeding user: {USER_ID}")
    users_table.put_item(Item={
        "user_id": USER_ID,
        "major":   MAJOR,
        # No subplan — ETI may not have subplans
    })
    print(f"  major: {MAJOR}")

def seed_transcript_from_pdf(pdf_path: str):
    from transcript_parser import parse_transcript
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    courses = parse_transcript(pdf_bytes)
    print(f"\nParsed {len(courses)} courses from {pdf_path}")
    return courses

def seed_transcript_from_hardcoded():
    """
    Matthew's real transcript as of 01/09/2026 (parsed from PDF).
    52 earned credits. Currently pre-major in IST, SP 2026 in progress.
    Note: MATH 140 F (FA 2024, grade forgiveness) excluded — only the
    passing repeat (SU 2025, C) is kept, which the parser handles automatically.
    A-I 100 (SP 2026) is excluded — the hyphenated dept code is not yet
    supported by the transcript parser regex.
    """
    courses = [
        # SU 2024
        {"course_code": "EDSGN 100", "grade": "A",  "credits_earned": 3.0, "credits": 3.0, "course_title": "Introduction to Engineering Design",         "term": "SU 2024", "status": "done"},
        {"course_code": "ENGL 15",   "grade": "B",  "credits_earned": 3.0, "credits": 3.0, "course_title": "Rhetoric and Composition",                   "term": "SU 2024", "status": "done"},
        # FA 2024
        {"course_code": "ANTH 140",  "grade": "B+", "credits_earned": 3.0, "credits": 3.0, "course_title": "Cultural Anthropology",                      "term": "FA 2024", "status": "done"},
        {"course_code": "CHEM 110",  "grade": "D",  "credits_earned": 3.0, "credits": 3.0, "course_title": "Chemical Principles I",                      "term": "FA 2024", "status": "done"},
        {"course_code": "ECON 102",  "grade": "B-", "credits_earned": 3.0, "credits": 3.0, "course_title": "Introductory Microeconomic Analysis",        "term": "FA 2024", "status": "done"},
        {"course_code": "ME 101",    "grade": "A",  "credits_earned": 1.0, "credits": 1.0, "course_title": "Introduction to Mechanical Engineering",     "term": "FA 2024", "status": "done"},
        # SP 2025
        {"course_code": "CAS 100C",  "grade": "B+", "credits_earned": 3.0, "credits": 3.0, "course_title": "Effective Speech",                           "term": "SP 2025", "status": "done"},
        {"course_code": "GEOSC 40",  "grade": "A",  "credits_earned": 3.0, "credits": 3.0, "course_title": "The Sea Around Us",                          "term": "SP 2025", "status": "done"},
        {"course_code": "METEO 3",   "grade": "A-", "credits_earned": 3.0, "credits": 3.0, "course_title": "Introductory Meteorology",                   "term": "SP 2025", "status": "done"},
        {"course_code": "MGMT 301",  "grade": "A-", "credits_earned": 3.0, "credits": 3.0, "course_title": "Basic Management Concepts",                  "term": "SP 2025", "status": "done"},
        {"course_code": "SCM 200",   "grade": "B+", "credits_earned": 4.0, "credits": 4.0, "course_title": "Introduction to Statistics for Business",    "term": "SP 2025", "status": "done"},
        # SU 2025
        {"course_code": "MATH 140",  "grade": "C",  "credits_earned": 4.0, "credits": 4.0, "course_title": "Calculus With Analytic Geometry I",          "term": "SU 2025", "status": "done"},
        # FA 2025
        {"course_code": "ACCTG 211", "grade": "C",  "credits_earned": 4.0, "credits": 4.0, "course_title": "Financial and Managerial Accounting",        "term": "FA 2025", "status": "done"},
        {"course_code": "ECON 104",  "grade": "C",  "credits_earned": 3.0, "credits": 3.0, "course_title": "Introductory Macroeconomic Analysis",        "term": "FA 2025", "status": "done"},
        {"course_code": "MKTG 301",  "grade": "C",  "credits_earned": 3.0, "credits": 3.0, "course_title": "Principles of Marketing",                    "term": "FA 2025", "status": "done"},
        {"course_code": "MUSIC 11",  "grade": "B+", "credits_earned": 3.0, "credits": 3.0, "course_title": "Introduction to Western Music",              "term": "FA 2025", "status": "done"},
        {"course_code": "THEA 101",  "grade": "B-", "credits_earned": 3.0, "credits": 3.0, "course_title": "Introduction to Theatre",                    "term": "FA 2025", "status": "done"},
        # SP 2026 (in progress)
        {"course_code": "CAMS 45",   "grade": "",   "credits_earned": 0.0, "credits": 3.0, "course_title": "The Ancient Mediterranean World",            "term": "SP 2026", "status": "in_progress"},
        {"course_code": "CMPSC 131", "grade": "",   "credits_earned": 0.0, "credits": 3.0, "course_title": "Programming and Computation I",              "term": "SP 2026", "status": "in_progress"},
        {"course_code": "HM 208",    "grade": "",   "credits_earned": 0.0, "credits": 3.0, "course_title": "Introduction to the Hospitality Industry",   "term": "SP 2026", "status": "in_progress"},
        {"course_code": "KINES 11",  "grade": "",   "credits_earned": 0.0, "credits": 1.5, "course_title": "Fitness and Wellness",                       "term": "SP 2026", "status": "in_progress"},
        {"course_code": "SOC 119",   "grade": "",   "credits_earned": 0.0, "credits": 3.0, "course_title": "Race, Ethnicity, and Culture",              "term": "SP 2026", "status": "in_progress"},
    ]
    return courses

def seed_courses(courses):
    print(f"\nSeeding {len(courses)} transcript courses for {USER_ID}...")
    with transcript_table.batch_writer() as batch:
        for c in courses:
            item = {
                "user_id":        USER_ID,
                "course_code":    c["course_code"],
                "grade":          c.get("grade", ""),
                "credits_earned": Decimal(str(c.get("credits_earned", 0))),
                "credits":        Decimal(str(c.get("credits", c.get("credits_earned", 0)) or 0)),
                "course_title":   c.get("course_title", ""),
                "term":           c.get("term", ""),
                "status":         c.get("status", "done"),
                "is_writing":     bool(c.get("is_writing")),
            }
            batch.put_item(Item=item)

    done = sum(1 for c in courses if c["status"] == "done")
    ip   = sum(1 for c in courses if c["status"] == "in_progress")
    tr   = sum(1 for c in courses if c["status"] == "transfer")
    print(f"  Done: {done}  In-Progress: {ip}  Transfer: {tr}")

def patch_eti_catalog():
    """
    Fix the ETI program's junk rows — the scraper captured credit counts ("3",
    "4") as course_title for some rows, creating duplicate entries that inflate
    the missing count.

    This used to also pair BA 243/BLAW 243, BA 301/FIN 301, BA 303/MKTG 301 and
    BA 304/MGMT 301 as choose_one (ids 580-583). That was wrong, and removing it
    is the point of this note.

    Those four either/or pairs are the **Business Competency application focus**
    ("Select 12 credits from: (BA 301 or FIN 100 or FIN 301), (BA 303 or MKTG
    221W or MKTG 301), (BA 304 or MGMT 100 or MGMT 301), BLAW 243, IB 303") —
    one of several optional focuses a student may choose, alongside Cybersecurity
    and HCDD. They are NOT the major requirement. The major requirement is a
    single pool, "Select 3-4 credits from the following:" over those same nine
    courses, and the bulletin footnote is explicit:

        Note 3: One of these courses is required to be taken to satisfy major
        requirements. The student needs to take the remaining courses on this
        list to complete the application focus. The student may not double-count
        these credits as both a requirement of the major and to meet the
        requirements of the application focus.

    So the patch took an optional focus and made it mandatory, telling every ETI
    student they owed four business courses instead of one — regardless of which
    focus they actually picked. Re-typing the rows to choose_one also destroyed
    the pool, which is how the requirement is genuinely modelled now that the
    scraper splits pools correctly (see `pool_seq` in scrape_psu.py).
    """
    print("\nPatching ETI catalog...")
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(MAJOR)
    )
    rows = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(MAJOR),
            ExclusiveStartKey=resp["LastEvaluatedKey"]
        )
        rows.extend(resp.get("Items", []))

    # 1. Delete junk rows where course_title is a bare number (credit count artifact)
    deleted = 0
    for r in rows:
        if str(r.get("course_title", "")).strip().isdigit():
            requirements_table.delete_item(
                Key={"program_name": r["program_name"], "group_course": r["group_course"]}
            )
            deleted += 1
    print(f"  Removed {deleted} junk rows (credit-count titles).")


def patch_phys_alternatives():
    """
    Fix catalog defect: PHYS 211 (calc-based sequence) and PHYS 250 (algebra-based sequence)
    appear as both 'required' in the same requirement group for 39 program+group combos.
    In reality, programs offer these as alternatives (students on the MATH 22 track take
    PHYS 250; others take PHYS 211). This patches them to 'choose_one' pairs.

    Pair IDs start at 600 (580-583 are retired — see patch_eti_catalog).
    """
    import re
    from boto3.dynamodb.conditions import Attr

    print("\nPatching PHYS 211 / PHYS 250 alternatives across all programs...")

    _CAMPUS_RE = re.compile(r" at [\w\s]+ campus", re.IGNORECASE)

    # Fetch all PHYS 211 and PHYS 250 rows
    def scan_code(code):
        resp = requirements_table.scan(FilterExpression=Attr("course_code").eq(code))
        rows = resp["Items"]
        while "LastEvaluatedKey" in resp:
            resp = requirements_table.scan(
                FilterExpression=Attr("course_code").eq(code),
                ExclusiveStartKey=resp["LastEvaluatedKey"]
            )
            rows.extend(resp["Items"])
        return rows

    phys211_rows = scan_code("PHYS 211")
    phys250_rows = scan_code("PHYS 250")

    # Index by (program_name, requirement_group) -> row
    from collections import defaultdict
    by_pg_211 = {}
    for r in phys211_rows:
        key = (r["program_name"], r["requirement_group"])
        by_pg_211[key] = r

    by_pg_250 = {}
    for r in phys250_rows:
        key = (r["program_name"], r["requirement_group"])
        by_pg_250[key] = r

    # Find all combos where both exist in the same group
    common_keys = set(by_pg_211.keys()) & set(by_pg_250.keys())

    # Exclude gen ed pool (it's already choose_credits, no pairing needed)
    # and skip campus-specific groups (they get filtered anyway)
    pair_id = Decimal("600")
    patched = 0
    skipped_already = 0

    for key in sorted(common_keys):
        prog, group = key
        if prog == "__GEN_ED__":
            continue

        row_211 = by_pg_211[key]
        row_250 = by_pg_250[key]

        # Skip if either is already paired
        if row_211.get("pair_group_id") or row_250.get("pair_group_id"):
            skipped_already += 1
            continue

        for row in (row_211, row_250):
            requirements_table.update_item(
                Key={"program_name": row["program_name"], "group_course": row["group_course"]},
                UpdateExpression="SET pair_group_id = :pid, group_type = :gt",
                ExpressionAttributeValues={":pid": pair_id, ":gt": "choose_one"},
            )
        pair_id += 1
        patched += 1

    print(f"  Patched {patched} PHYS 211/250 alternative pairs across programs.")
    if skipped_already:
        print(f"  Skipped {skipped_already} pairs (already patched).")


# ── Define all known alternative groups ───────────────────────────────────
#
# Each entry:
#   codes         - list of course codes that are interchangeable (2 or 3)
#   insert_missing - if True, insert an absent alternative when only 1 is present —
#                    but ONLY where program_data/alternative_inserts.json verified
#                    that program's bulletin offers it (see _verified_inserts()).
#                    Unverified, this added CHEM 130 to Chemical Engineering and
#                    MATH 110 to Physics: 280 alternatives no bulletin offered.
#   exclude        - fn(program_name, group_name) -> bool; True = skip this combo
#
# "MIXED" pairs (both sometimes required) use insert_missing=False and an
# exclude function to protect programs where both courses are genuinely needed.

KNOWN_ALTERNATIVE_GROUPS = [
    # ── English / Writing ───────────────────────────────────────────────
    dict(codes=["ENGL 202C", "ENGL 202D"],
         insert_missing=True, exclude=None),

    # ── Speech (3-way: A, B, C are all sections of the same course) ─────
    dict(codes=["CAS 100A", "CAS 100B", "CAS 100C"],
         insert_missing=True, exclude=None),

    # ── Statistics ──────────────────────────────────────────────────────
    dict(codes=["STAT 200", "STAT 250"],
         insert_missing=True, exclude=None),
    dict(codes=["SCM 200",  "STAT 200"],
         insert_missing=False, exclude=None),
    dict(codes=["DS 200",   "STAT 200"],
         insert_missing=True, exclude=None),

    # ── Chemistry ───────────────────────────────────────────────────────
    dict(codes=["CHEM 110", "CHEM 130"],
         insert_missing=True, exclude=None),
    dict(codes=["CHEM 101", "CHEM 130"],
         insert_missing=True, exclude=None),
    # Organic chem: MIXED — genuinely both required in Chemistry Teaching,
    # Clinical Lab Science, and Data Sciences Nutrition tracks
    dict(codes=["CHEM 202", "CHEM 210"],
         insert_missing=False,
         exclude=lambda p, g: (
             "Chemistry Teaching" in g or
             "Clinical Laboratory Science" in g or
             ("Data Sciences" in p and "Nutrition" in g)
         )),

    # ── Mathematics ─────────────────────────────────────────────────────
    dict(codes=["MATH 110", "MATH 140"],
         insert_missing=True, exclude=None),
    dict(codes=["MATH 250", "MATH 251"],
         insert_missing=True, exclude=None),
    # MATH 230/231 MIXED: most engineering programs require both as a sequence;
    # only minors and EET treat them as alternatives
    dict(codes=["MATH 230", "MATH 231"],
         insert_missing=False,
         exclude=lambda p, g: "Meteorology" in p and "Common Requirements" in g),

    # ── Accounting ──────────────────────────────────────────────────────
    dict(codes=["ACCTG 201", "ACCTG 211"],
         insert_missing=True, exclude=None),

    # ── Computer Science ─────────────────────────────────────────────────
    dict(codes=["CMPSC 121", "CMPSC 131"],
         insert_missing=True, exclude=None),
    dict(codes=["CMPSC 122", "CMPSC 132"],
         insert_missing=True, exclude=None),
    dict(codes=["CMPSC 200", "CMPSC 201"],
         insert_missing=True, exclude=None),
    dict(codes=["CMPSC 360", "MATH 311W"],
         insert_missing=True, exclude=None),

    # ── Business ────────────────────────────────────────────────────────
    dict(codes=["MIS 204",   "MIS 250"],
         insert_missing=True, exclude=None),
    dict(codes=["BA 243",    "BLAW 243"],
         insert_missing=False, exclude=None),
    dict(codes=["AGBM 101",  "ECON 102"],
         insert_missing=False, exclude=None),
    # ECON MIXED: both required in Business Common Req, Management Common Req,
    # Risk Management, Stats Actuarial, Criminology, lang+Business options,
    # and Data Sciences Economics/Business Fundamentals groups
    dict(codes=["ECON 102", "ECON 104"],
         insert_missing=False,
         exclude=lambda p, g: (
             ("Business, B.S." in p and "Common Requirements" in g) or
             ("Management, B.S." in p and "Common Requirements" in g) or
             "Risk Management" in p or
             ("Statistics, B.S." in p and "Actuarial" in g) or
             "Criminology" in p or
             (any(lang in p for lang in ["French", "German", "Spanish"]) and "Business" in g) or
             ("Data Sciences" in p and any(x in g for x in ["Economics", "Business Fundamentals"]))
         )),

    # ── Physics ─────────────────────────────────────────────────────────
    dict(codes=["PHYS 211", "PHYS 250"],
         insert_missing=True, exclude=None),
    dict(codes=["PHYS 212", "PHYS 251"],
         insert_missing=True, exclude=None),
    dict(codes=["PHYS 150", "PHYS 250"],
         insert_missing=True, exclude=None),

    # ── Biology ─────────────────────────────────────────────────────────
    dict(codes=["BIOL 222", "BIOL 322"],
         insert_missing=True, exclude=None),

    # ── Human Development / Psychology ───────────────────────────────────
    dict(codes=["HDFS 229", "PSYCH 100"],
         insert_missing=False, exclude=None),
]


def _verified_inserts() -> dict:
    """(program, group, code) -> verdict entry for every alternative the bulletin
    was checked for (scripts/verify_alternative_inserts.py). Only `keep` and
    `branch` entries may be inserted; anything absent from the file is not."""
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "program_data", "alternative_inserts.json")
    try:
        entries = json.load(open(path, encoding="utf-8"))["entries"]
    except FileNotFoundError:
        return {}
    return {(e["program"], e["group"], e["inserted"]): e for e in entries
            if e["verdict"] in ("keep", "branch")}


def patch_known_alternatives():
    """
    Fix choose-one alternative pairing defects across the entire catalog.

    The scraper inconsistently captured known interchangeable course alternatives as:
    both required in the same group (no pair), only one present (other absent), or
    both choose_one but without a pair_group_id linking them.

    Strategy per (program, group):
      - 2+ courses present + unpaired -> assign shared pair_group_id, set to choose_one
      - 1 course present + insert_missing=True -> insert an absent alternative, then
        pair — only where program_data/alternative_inserts.json verified the bulletin
        offers it; a `branch` verdict inserts the whole compound branch
        ("ACCTG 211 or (ACCTG 201 and ACCTG 202)") under one pair_branch_id
      - choose_credits pools -> skip (pairing doesn't apply to credit pools)
      - excluded combos -> skip (courses are genuinely both required there)
      - already paired -> skip (idempotent)

    One full table scan is performed upfront; all filtering happens in Python.

    Pair IDs:
      ETI pairs:        580-583  (retired, see patch_eti_catalog)
      PHYS 211/250:     600+
      MATH 250/251:     700+   (already applied, will be skipped as already-paired)
      This function:    800+
    """
    from collections import defaultdict

    print("\nPatching known course alternatives across all programs...")

    GROUPS = KNOWN_ALTERNATIVE_GROUPS

    # ── One full table scan, filter in Python ────────────────────────────────
    all_relevant_codes = set()
    for grp in GROUPS:
        all_relevant_codes.update(grp["codes"])

    print(f"  Scanning catalog for {len(all_relevant_codes)} course codes...")
    resp = requirements_table.scan()
    all_rows = resp["Items"]
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        all_rows.extend(resp["Items"])

    rows_by_code = defaultdict(list)
    for row in all_rows:
        if row.get("course_code") in all_relevant_codes:
            rows_by_code[row["course_code"]].append(row)

    # Build (program, group) -> row index per code
    by_pg = {
        code: {(r["program_name"], r["requirement_group"]): r for r in rows}
        for code, rows in rows_by_code.items()
    }

    # Course info cache for insertion (title + credits). The catalog contains
    # junk titles (credit ranges like "1-0" imported as course_title), and scan
    # order is arbitrary — picking rows[0] made inserted-row titles
    # nondeterministic (caught as a local-vs-prod audit diff on ACCTG 201).
    # Pick the most common non-junk title instead.
    import re as _re
    from collections import Counter

    _junk_title = lambda t: not t or _re.fullmatch(r"[\d\s./-]*", str(t).strip()) is not None

    course_info = {}
    for code, rows in rows_by_code.items():
        if not rows:
            continue
        good = [str(r["course_title"]).strip() for r in rows
                if not _junk_title(r.get("course_title"))]
        if good:
            title = Counter(good).most_common(1)[0][0]
            credits = next((r.get("credits") for r in rows
                            if str(r.get("course_title", "")).strip() == title
                            and r.get("credits") is not None), Decimal("3"))
        else:
            title   = rows[0].get("course_title", "")
            credits = rows[0].get("credits", Decimal("3"))
        course_info[code] = (title, credits)

    # Repair junk titles on existing rows for these codes (fixes rows inserted
    # by earlier runs of this patch that inherited a junk title).
    repaired = 0
    for code, rows in rows_by_code.items():
        best = course_info.get(code, ("",))[0]
        if _junk_title(best):
            continue
        for r in rows:
            if _junk_title(r.get("course_title")):
                requirements_table.update_item(
                    Key={"program_name": r["program_name"], "group_course": r["group_course"]},
                    UpdateExpression="SET course_title = :t",
                    ExpressionAttributeValues={":t": best},
                )
                repaired += 1
    if repaired:
        print(f"  Repaired {repaired} junk course titles.")

    # ── Apply each group ─────────────────────────────────────────────────────
    pair_id = Decimal("800")
    total_patched = 0
    skipped_already = 0
    skipped_pool = 0
    skipped_excluded = 0

    def assign_pair(rows_to_update):
        nonlocal pair_id, total_patched
        for row in rows_to_update:
            requirements_table.update_item(
                Key={"program_name": row["program_name"], "group_course": row["group_course"]},
                UpdateExpression="SET pair_group_id = :pid, group_type = :gt",
                ExpressionAttributeValues={":pid": pair_id, ":gt": "choose_one"},
            )
            # Write the assignment back onto the cached dict as well. `by_pg` is a
            # snapshot taken before any of these updates, and the "skip if already
            # paired" guard below reads it — so without this, a course appearing in
            # two GROUPS entries gets re-paired by the second one and its first
            # partner is orphaned in a pair of its own. A lone choose_one row reads
            # as individually REQUIRED, so the orphan becomes a phantom
            # requirement: STAT 200 sits in three entries, which stranded STAT 250
            # in 191 University Park majors (262 singleton pairs in total).
            row["pair_group_id"] = pair_id
            row["group_type"]    = "choose_one"
        pair_id += 1
        total_patched += 1

    verified = _verified_inserts()
    bulletin = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "bulletin_courses.json"), encoding="utf-8"))
    skipped_unverified = 0

    def insert_course(template_row, code, branch_id=None):
        if code in course_info and course_info[code][0] is not None:
            title, credits = course_info[code]
        elif code in bulletin:               # a branch mate outside GROUPS (ACCTG 202)
            title, credits = bulletin[code]["title"], Decimal(str(bulletin[code]["credits"]))
        else:
            return None
        item = {k: v for k, v in template_row.items()}
        item["course_code"]  = code
        item["course_title"] = title
        item["credits"]      = credits
        item["group_course"] = f"{template_row['requirement_group']}#{code}"
        item.pop("pair_group_id", None)
        item.pop("pair_branch_id", None)
        if branch_id:
            item["pair_branch_id"] = branch_id
        requirements_table.put_item(Item=item)
        return item

    for grp in GROUPS:
        codes        = grp["codes"]
        insert_miss  = grp["insert_missing"]
        exclude_fn   = grp.get("exclude")
        grp_patched  = 0

        # Union of all (program, group) keys where any code in this group appears
        all_keys = set()
        for code in codes:
            all_keys.update(by_pg.get(code, {}).keys())

        for key in sorted(all_keys):
            prog, group = key
            if prog == "__GEN_ED__":
                continue

            if exclude_fn and exclude_fn(prog, group):
                skipped_excluded += 1
                continue

            present = {c: by_pg.get(c, {}).get(key) for c in codes}
            present = {c: r for c, r in present.items() if r is not None}

            # Skip if any row is already paired
            if any(r.get("pair_group_id") for r in present.values()):
                skipped_already += 1
                continue

            # Skip choose_credits pools
            if any(r.get("group_type") == "choose_credits" for r in present.values()):
                skipped_pool += 1
                continue

            if len(present) >= 2:
                assign_pair(list(present.values()))
                grp_patched += 1
            elif len(present) == 1 and insert_miss:
                template = list(present.values())[0]
                new_rows = [template]
                for mc in [c for c in codes if c not in present]:
                    entry = verified.get((prog, group, mc))
                    if entry is None:
                        skipped_unverified += 1      # the bulletin never offers it here
                        continue
                    # "ACCTG 211 or (ACCTG 201 and ACCTG 202)": ACCTG 201 alone is
                    # half a course, so the whole branch goes in under one branch id.
                    members = entry["branch"] or [mc]
                    branch_id = f"alt-{pair_id}" if entry["branch"] else None
                    for code in members:
                        nr = insert_course(template, code, branch_id)
                        if nr:
                            new_rows.append(nr)
                if len(new_rows) >= 2:
                    assign_pair(new_rows)
                    grp_patched += 1

        if grp_patched:
            label = " / ".join(codes)
            print(f"  {label}: {grp_patched} groups fixed.")

    print(f"\n  Total: {total_patched} groups patched.")
    if skipped_already:
        print(f"  Skipped {skipped_already} already-paired.")
    if skipped_pool:
        print(f"  Skipped {skipped_pool} choose_credits pools.")
    if skipped_excluded:
        print(f"  Skipped {skipped_excluded} excluded (both-required) combos.")
    if skipped_unverified:
        print(f"  Skipped {skipped_unverified} alternatives the bulletin does not offer.")


# `patch_eti_select_groups()` lived here. It diagnosed this exact bug in ETI —
# "bulletin has 3 pools, scraper made 1" — and worked around it by re-typing two
# of the merged pools into choose_one pairs (ids 590, 591).
#
# The scraper now splits pools properly (`pool_seq`), so ETI's six pools arrive
# as six pools and the workaround is not only redundant but harmful: its guard
# fires on any `choose_credits` row without a pair id, so it would re-type the
# now-correct CMPSC 122 / CMPSC 132 / IST 242 pool back into a pair and undo the
# fix on every seed. Its third group (ETI 435 / ETI 463 / IST 440W) was wrong on
# its own terms too — the bulletin pairs ETI 400/423 and ETI 435/463 as ordinary
# "or" rows, which the scraper captures, and never lists IST 440W here at all.


def patch_choose_credits_option_groups():
    """
    Fix catalog defect: option groups named 'X Option (N credits)' where the scraper
    captured each listed course as 'required', but the group is actually a choose_credits
    pool (student picks enough courses to total N credits).

    Detection: group name contains '(N credits)' or '(N-M credits)' AND the sum of
    listed course credits exceeds N*1.4 (i.e., far more courses than could be required
    given the credit cap).

    Fixes: set group_type='choose_credits' and group_threshold=N for all rows in the group.
    """
    import re
    from collections import defaultdict

    print("\nPatching choose_credits option groups...")

    _CR_RE = re.compile(r'\((\d+)(?:-(\d+))?\s+credits?\)', re.IGNORECASE)

    resp = requirements_table.scan()
    rows = resp["Items"]
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        rows.extend(resp["Items"])

    by_pg: dict = defaultdict(list)
    for r in rows:
        # Sentinel rows (__GEN_ED__, __CROSSLISTINGS__) are not requirement rows.
        # __CROSSLISTINGS__ in particular carries `pairs`/`pair_count` and has no
        # requirement_group at all, so indexing it blindly raises KeyError. This
        # never fires locally — the dev DB is rebuilt from scratch and the
        # sentinel is only written by the monthly refresh — but it kills the
        # script against prod, where the sentinel is preserved across reloads.
        if str(r.get("program_name", "")).startswith("__"):
            continue
        if "requirement_group" not in r:
            continue
        key = (r["program_name"], r["requirement_group"])
        by_pg[key].append(r)

    patched_groups = 0
    patched_rows = 0
    skipped = 0

    for (prog, group), group_rows in by_pg.items():
        m = _CR_RE.search(group)
        if not m:
            continue
        threshold = int(m.group(1))
        total_cr = sum(float(r.get("credits", 3) or 3) for r in group_rows)
        types = set(r.get("group_type", "") for r in group_rows)

        if total_cr <= threshold * 1.4 or types != {"required"}:
            skipped += 1
            continue

        for r in group_rows:
            requirements_table.update_item(
                Key={"program_name": r["program_name"], "group_course": r["group_course"]},
                UpdateExpression="SET group_type = :gt, group_threshold = :thr",
                ExpressionAttributeValues={":gt": "choose_credits", ":thr": Decimal(str(threshold))},
            )
            patched_rows += 1
        patched_groups += 1

    print(f"  Patched {patched_groups} option groups ({patched_rows} rows) to choose_credits.")


# ── Adviser-defined majors ───────────────────────────────────────────────────
# Two UP majors publish no course list at all, only credit buckets the student
# fills with an adviser. The scraper captured just their Suggested Academic Plan
# grid cells ("... at University Park Campus"), which routers.audit._filter_rows
# drops as plan duplicates, so their audit was empty ("0 remaining"). Each
# bucket is modelled as one `unstructured_credits` row: never auto-satisfied,
# carries PSU's wording, flagged needs_confirmation by the engine.
#
# Source: the "Program Requirements" tab, read Oct 6 2026 —
#   https://bulletins.psu.edu/undergraduate/colleges/arts-architecture/integrative-arts-ba/
#   https://bulletins.psu.edu/undergraduate/colleges/liberal-arts/multidisciplinary-studies-ba/
# Group names start with "Requirements for the Major" (PSU's heading) so
# routers.audit.get_subplans skips them instead of offering them as tracks, and
# avoid "option", "common", "(N credits)" and "at ... Campus" so no other
# filter or patch reinterprets them.
ADVISER_DEFINED_MAJORS = {
    "Integrative Arts, B.A. (Arts and Architecture)": {
        "college": "Arts Architecture",
        "degree":  "B.A.",
        "groups": [
            ("Requirements for the Major: Primary Arts Area", 24,
             "Select 24 credits from an arts area. Requirements for the Major: "
             "Must include at least 15 credits at the 400 or equivalent level. "
             "Must include 6 credits in History of the Arts."),
            ("Requirements for the Major: Other Arts Areas", 12,
             "Select 12 credits from other arts areas"),
            ("Requirements for the Major: Arts (GA)", 6,
             "Select 6 credits of GA"),
        ],
    },
    "Multidisciplinary Studies, B.A. (Liberal Arts)": {
        "college": "Liberal Arts",
        "degree":  "B.A.",
        "groups": [
            ("Requirements for the Major: University-wide Offerings", 24,
             "Select 24 credits from University-wide offerings to include: "
             "12 credits at the 400 level representing at least three different "
             "subject areas; 3 credit 400-level capstone course; A minimum 9 "
             "credits from the humanities and social sciences. Courses must be "
             "selected in consultation with an adviser."),
            ("Requirements for the Major: Research Methods/Projects", 3,
             "Select 3 credits in research methods/projects from courses that "
             "involve research methodology or that focus on a research project"),
            ("Requirements for the Major: Communication Skills", 3,
             "Select 3 credits in communication skills from courses that focus on "
             "expression including those in verbal, symbolic, and written skills"),
            ("Requirements for the Major: Theory/Application", 3,
             "Select 3 credits in theory/application from courses that focus on "
             "theory, principle, central concepts, or fundamental issues"),
            ("Requirements for the Major: Critical Analysis", 3,
             "Select 3 credits in critical analysis from courses that focus on "
             "evaluation, synthesis, and analysis"),
        ],
    },
}

ADVISER_DEFINED_CODE = "__ADVISER_DEFINED__"


def adviser_defined_rows() -> list[dict]:
    """The requirement rows patch_adviser_defined_majors() writes (pure, no DB).
    Same sentinel-row shape as credential_catalog._pool_row."""
    rows = []
    for program, spec in ADVISER_DEFINED_MAJORS.items():
        for group, credits, text in spec["groups"]:
            rows.append({
                "program_name":      program,
                "group_course":      f"{group}#{ADVISER_DEFINED_CODE}",
                "requirement_group": group,
                "group_type":        "unstructured_credits",
                "group_threshold":   Decimal(str(credits)),
                "course_code":       ADVISER_DEFINED_CODE,
                "course_title":      text,
                "credits":           Decimal(str(credits)),
                "min_grade":         "C",
                "pool_text":         text,
                "pool_seq":          Decimal("1"),
                "college":           spec["college"],
                "degree":            spec["degree"],
            })
    return rows


def patch_adviser_defined_majors():
    """Write one unstructured_credits row per bucket. Idempotent: fixed keys,
    put_item overwrites. The scraped plan-grid rows are left alone (the audit
    filter already drops them)."""
    print("\nPatching adviser-defined majors (Integrative Arts, Multidisciplinary Studies)...")
    rows = adviser_defined_rows()
    for row in rows:
        requirements_table.put_item(Item=row)
    print(f"  Wrote {len(rows)} unstructured_credits rows "
          f"across {len(ADVISER_DEFINED_MAJORS)} programs.")


# ── Level / subject pools the scraper turned into fake course codes ──────────
# Bulletin prose rules ("Select 12 credits from the following ranges:
# Archaeology: ANTH 420-439 …", "400-level CMPSC (other than …)", "Any LER
# 400-level course") were read as courses: the scraper took the first number in
# the line, inventing ANTH 400 / 420 / 440, a "400-level CMPSC" CMPSC 451, LER 400
# and so on, or dropped the line entirely. Pools built on them could never reach
# their threshold, and in Anthropological Science the fake codes were even stored
# as individually REQUIRED courses. Each spec below repairs one requirement group:
#
#   pools       -> `dept_credits` rows (the engine's subject/level rule, same
#                  sentinel shape as credential_catalog._pool_row); courses the
#                  rule names outright go in `include`.
#   expand      -> a rule that sits INSIDE a course-list pool ("Select 15 credits
#                  from …, Any LER 400-level course") can't be a separate rule row
#                  (a different group_type is a separate requirement), so the
#                  real bulletin courses it covers are added to that pool as
#                  ordinary choose_credits rows.
#   choose_one  -> a named course whose bulletin wording allows alternatives
#                  ("MATH 22 or placement beyond MATH 22") becomes a choose-one
#                  over real courses, never a hard requirement.
#
# A major audit is NOT exclusive (unlike credentials), so a course can count in
# two pools of one major. That is what makes Anthropology's "12 credits, at least
# 3 in each range" exact: one 12-credit pool over every range plus a 3-credit
# pool per range, all seeing the same courses. Courses PRESCRIBED in the same
# section are excluded from the "additional" pools (PSU's heading is "Additional
# Courses"), so CMPSC 465 can't also fill Statistics' 9 credits.
#
# Guard: a spec only deletes when the scraped rows it was written against are
# still there (`replaces` = a whole pool by pool_seq holding only those codes;
# `invented` = (code, title regex) rows). If they are gone and the patch's own
# rows are absent too, a re-scrape changed the page and the spec is skipped.
#
# Source: the "Program Requirements" tab, read Oct 6 2026 —
#   https://bulletins.psu.edu/undergraduate/colleges/liberal-arts/anthropology-ba/
#   https://bulletins.psu.edu/undergraduate/colleges/liberal-arts/anthropological-science-bs/
#   https://bulletins.psu.edu/undergraduate/colleges/eberly-science/statistics-bs/
#   https://bulletins.psu.edu/undergraduate/colleges/liberal-arts/criminology-bs/
#   https://bulletins.psu.edu/undergraduate/colleges/liberal-arts/psychology-bs/
#   https://bulletins.psu.edu/undergraduate/colleges/health-human-development/human-development-family-studies-bs/
#   https://bulletins.psu.edu/undergraduate/colleges/health-human-development/kinesiology-bs/
#   https://bulletins.psu.edu/undergraduate/colleges/liberal-arts/linguistics-ba/
#   https://bulletins.psu.edu/undergraduate/colleges/eberly-science/physics-bs/

def _nums(dept: str, *ranges: tuple[int, int], skip: tuple[int, ...] = ()) -> list[str]:
    """Every course number in the inclusive ranges, as codes ("ANTH 420"…). The
    engine excludes on (subject, number), so this also covers suffixed twins."""
    return [f"{dept} {n}" for lo, hi in ranges for n in range(lo, hi + 1) if n not in skip]


_ANTH_ARCH = "Archaeology: ANTH 420-439"
_ANTH_BIO  = "Biological anthropology: ANTH 400-419, ANTH 460-473"
_ANTH_CULT = "Human Ecology/Cultural anthropology: ANTH 440-459, ANTH 474-479"
_ANTH_SURVEY_EXCLUDE = (["ANTH 1", "ANTH 83", "ANTH 2", "ANTH 21", "ANTH 45"]
                        + _nums("ANTH", (190, 199), (290, 299), skip=(297,)))
_ANTH_SURVEY_TEXT = ("Select 6 credits in ANTH courses at the 200 level or below (excluding "
                     "ANTH 1, ANTH 83S, and courses in the following ranges: 190-199, "
                     "290-299, other than 297)")


def _anth_ranges(tag: str, arch: int, bio: int, cult: int, seq0: int = 1) -> list[dict]:
    """Anthropology's three ANTH 400-level ranges as dept_credits pools."""
    return [
        {"tag": f"{tag}_ARCH", "threshold": arch, "pool_seq": seq0, "dept": "ANTH",
         "min_level": 420, "max_level": 439,
         "text": f"Select {arch} credits in {_ANTH_ARCH}"},
        {"tag": f"{tag}_BIO", "threshold": bio, "pool_seq": seq0 + 1, "dept": "ANTH",
         "min_level": 400, "max_level": 473, "exclude": _nums("ANTH", (420, 459)),
         "text": f"Select {bio} credits in {_ANTH_BIO}"},
        {"tag": f"{tag}_CULT", "threshold": cult, "pool_seq": seq0 + 2, "dept": "ANTH",
         "min_level": 440, "max_level": 479, "exclude": _nums("ANTH", (460, 473)),
         "text": f"Select {cult} credits in {_ANTH_CULT}"},
    ]


_ANTH_SCI = "Anthropological Science, B.S."
_ANTH_SCI_FAKE = [("ANTH 400", r"-419"), ("ANTH 420", r"-439"), ("ANTH 440", r"-459")]
_LER_400 = {"pool_seq": 1, "threshold": 15, "ranges": [("LHR", 400, 499), ("LER", 400, 499)]}

LEVEL_POOLS = [
    {
        "program": "Anthropology, B.A.",
        "group":   "Requirements for the Major",
        # The invented pool: pool_seq 3, these codes only (the guard below).
        "replaces": {"pool_seq": 3, "codes": {"ANTH 400", "ANTH 420", "ANTH 440"}},
        "pools": [
            # "Area/Survey Courses" — a prose-only pool the scraper dropped outright.
            {"tag": "ANTH_SURVEY", "threshold": 6, "pool_seq": 1, "dept": "ANTH", "max_level": 299,
             "exclude": _ANTH_SURVEY_EXCLUDE, "text": _ANTH_SURVEY_TEXT},
            {"tag": "ANTH_ADVANCED", "threshold": 12, "pool_seq": 3, "dept": "ANTH",
             "min_level": 400, "max_level": 479,
             "text": "Select 12 credits from the following ranges (at least 3 credits must be "
                     f"in each range): {_ANTH_ARCH}; {_ANTH_BIO}; {_ANTH_CULT}"},
            {"tag": "ANTH_ARCH", "threshold": 3, "pool_seq": 101, "dept": "ANTH",
             "min_level": 420, "max_level": 439,
             "text": f"At least 3 credits in {_ANTH_ARCH}"},
            {"tag": "ANTH_BIO", "threshold": 3, "pool_seq": 102, "dept": "ANTH",
             "min_level": 400, "max_level": 473, "exclude": _nums("ANTH", (420, 459)),
             "text": f"At least 3 credits in {_ANTH_BIO}"},
            {"tag": "ANTH_CULT", "threshold": 3, "pool_seq": 103, "dept": "ANTH",
             "min_level": 440, "max_level": 479, "exclude": _nums("ANTH", (460, 473)),
             "text": f"At least 3 credits in {_ANTH_CULT}"},
        ],
    },
    # Anthropological Science: the same ranges, sized per option, stored as three
    # REQUIRED fake courses per option. Within an option the ranges are disjoint.
    {"program": _ANTH_SCI, "group": "Archaeological Science Option (33 credits)",
     "invented": _ANTH_SCI_FAKE, "pools": _anth_ranges("ANTHSCI_ARCHOPT", 12, 3, 3)},
    {"program": _ANTH_SCI, "group": "Biological Anthropology Option (33 credits)",
     "invented": _ANTH_SCI_FAKE, "pools": _anth_ranges("ANTHSCI_BIOOPT", 3, 12, 3)},
    {"program": _ANTH_SCI, "group": "Human Ecology Option (33 credits)",
     "invented": _ANTH_SCI_FAKE, "pools": _anth_ranges("ANTHSCI_HEOPT", 3, 3, 12)},
    {"program": _ANTH_SCI, "group": "Integrated Anthropological Science Option (33 credits)",
     "invented": _ANTH_SCI_FAKE, "pools": _anth_ranges("ANTHSCI_INTOPT", 6, 6, 6)},
    # The same dropped "Area/Survey" pool as Anthropology B.A.; nothing to delete.
    {"program": _ANTH_SCI, "group": "Common Requirements for the Major (All Options)",
     "invented": [],
     "pools": [{"tag": "ANTHSCI_SURVEY", "threshold": 6, "pool_seq": 1, "dept": "ANTH",
                "max_level": 299, "exclude": _ANTH_SURVEY_EXCLUDE, "text": _ANTH_SURVEY_TEXT}]},
    {
        "program": "Statistics, B.S.",
        "group":   "Statistics and Computing Option (41 credits)",
        "replaces": {"pool_seq": 1, "codes": {"CMPSC 221", "CMPSC 451"}},
        "pools": [
            {"tag": "CMPSC_400", "threshold": 9, "pool_seq": 1, "dept": "CMPSC",
             "min_level": 400, "max_level": 499, "include": ["CMPSC 221"],
             # 451/455 per the bulletin (cross-listed MATH 451/455 resolve to these);
             # 465 is prescribed in this option.
             "exclude": ["CMPSC 451", "CMPSC 455", "CMPSC 465"],
             "text": "Select 9 credits from the following: CMPSC 221; 400-level CMPSC "
                     "(other than CMPSC 451/MATH 451 or CMPSC 455/MATH 455)"},
        ],
    },
    {
        "program": "Criminology, B.S.",
        "group":   "Social Science Research Option (22-23 credits)",
        "replaces": {"pool_seq": 2, "codes": {"HDFS 401", "PLSC 490"}},
        "pools": [
            {"tag": "STAT_400", "threshold": 9, "pool_seq": 2, "dept": "STAT",
             "min_level": 400, "max_level": 499, "include": ["HDFS 401", "PLSC 490"],
             "exclude": ["STAT 480"],            # prescribed in this option
             "text": "Select 9 credits of the following: HDFS 401; PLSC 490; "
                     "Any 400-level STAT course"},
        ],
    },
    # "Any LER 400-level course" inside a 15-credit list pool. LER was renamed LHR
    # and the bulletin carries both, so both subjects' 400-level courses join it.
    {"program": "Criminology, B.S.", "group": "Business/Public Administration Option (21 credits)",
     "invented": [("LER 400", r"level course")], "expand": _LER_400},
    {"program": "Psychology, B.S. (Liberal Arts)", "group": "Business Option (24 credits)",
     "invented": [("LER 400", r"level course")], "expand": _LER_400},
    # Research Emphasis: "6 Additional Credits of 300-/400-Level Research Credits
    # (e.g. HDFS 300H, HDFS 310M, HDFS 494, HDFS 494H, HDFS 496) or … Career-Related
    # Course Work (with Department Approval)" was filed as one HDFS 300H row. The
    # named examples join the pool (494/494H/496 already are); "with Department
    # Approval" isn't modelled.
    {"program": "Human Development and Family Studies, B.S. (Health and Human Development)",
     "group": "Common Requirements for the Major (All Options)",
     "invented": [("HDFS 300H", r"Additional Credits")],
     "expand": {"pool_seq": 5, "threshold": 15, "codes": ["HDFS 300H", "HDFS 310M"]}},
    # "MATH 22 or Satisfactory performance on the MATH placement examination --
    # i.e., placement beyond the level of MATH 22", stored as MATH 22 REQUIRED. The
    # alternatives are the higher courses the same page names for this requirement
    # in the other options (MATH 26, 40, 41, 110, 140). Placement with no course
    # taken is invisible to the audit.
    {"program": "Kinesiology, B.S. (Health and Human Development)",
     "group": "Exercise Science Option (55-58 credits)",
     "invented": [("MATH 22", r"placement")],
     "choose_one": {"pair": 9900001,
                    "codes": ["MATH 22", "MATH 26", "MATH 40", "MATH 41", "MATH 110", "MATH 140"]},
     # "Select 3 credits from KINES 1 to KINES 99" — dropped by the scraper.
     "pools": [{"tag": "KINES_1_99", "threshold": 3, "pool_seq": 101, "dept": "KINES",
                "min_level": 1, "max_level": 99,
                "text": "Select 3 credits from KINES 1 to KINES 99"}]},
    # "STAT 200 or appropriate statistics course": the alternatives are the intro
    # statistics courses the catalog treats as interchangeable with STAT 200
    # everywhere else (KNOWN_ALTERNATIVE_GROUPS).
    {"program": "Linguistics, B.A.", "group": "Requirements for the Major",
     "invented": [("STAT 200", r"appropriate")],
     "choose_one": {"pair": 9900002, "codes": ["STAT 200", "STAT 250", "SCM 200", "DS 200"]}},
    # Nanotechnology Set A: "6 credits from ESC 400-level courses", stored as ESC 400
    # (a real course, Electromagnetic Fields) with the sentence as its title.
    {"program": "Physics, B.S. (Science)",
     "group": "Nanotechnology/Material Science Option (24-25 credits)",
     "invented": [("ESC 400", r"Supporting Course")],
     "expand": {"pool_seq": 1, "threshold": 12, "ranges": [("ESC", 400, 499)]}},
]

LEVEL_POOL_CODE = "__DEPT_CREDITS_{tag}__"
_LEVEL_KEY = "LVLPATCH"          # rows this patch writes: "<group>#<code>#LVLPATCH"


def _bulletin() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bulletin_courses.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _expand_codes(exp: dict, bulletin: dict) -> list[str]:
    """The real bulletin courses an in-pool level rule stands for. A suffixed twin
    (ESC 460M / 460W) is listed once; the engine matches suffixes anyway."""
    import re as _re
    codes = list(exp.get("codes", []))
    for dept, lo, hi in exp.get("ranges", []):
        for code in sorted(bulletin):
            m = _re.fullmatch(rf"{_re.escape(dept)} (\d+)([A-Z]*)", code)
            if m and lo <= int(m.group(1)) <= hi:
                codes.append(code)
    out, seen = [], set()
    for code in codes:
        base = _re.sub(r"(\d)[WHMNXY]$", r"\1", code)
        if base not in seen:
            seen.add(base)
            out.append(code)
    return out


def level_pool_rows(spec: dict | None = None) -> list[dict]:
    """The rows patch_level_pools() writes (pure, no DB) — every spec's, or one's."""
    bulletin = None
    out = []
    for s in ([spec] if spec else LEVEL_POOLS):
        base = {"program_name": s["program"], "requirement_group": s["group"], "min_grade": "C"}
        for p in s.get("pools", []):
            code = LEVEL_POOL_CODE.format(tag=p["tag"])
            row = {
                **base,
                "group_course":      f"{s['group']}#{code}",
                "group_type":        "dept_credits",
                "group_threshold":   Decimal(str(p["threshold"])),
                "course_code":       code,
                "course_title":      p["text"],
                "credits":           Decimal(str(p["threshold"])),
                "pool_text":         p["text"],
                "pool_seq":          Decimal(str(p["pool_seq"])),
                "dept":              p["dept"],
            }
            for k in ("min_level", "max_level"):
                if p.get(k) is not None:
                    row[k] = Decimal(str(p[k]))
            for k in ("exclude", "include"):
                if p.get(k):
                    row[k] = list(p[k])
            out.append(row)
        if s.get("expand") or s.get("choose_one"):
            bulletin = bulletin or _bulletin()

        def course_row(code, **kw):
            # HDFS 300H is keyed HDFS 300 in the bulletin (an attribute suffix).
            info = (bulletin.get(code)
                    or bulletin.get(code[:-1] if code[-1:] in "WHMN" else code) or {})
            return {**base, "group_course": f"{s['group']}#{code}#{_LEVEL_KEY}",
                    "course_code": code, "course_title": info.get("title", ""),
                    "credits": Decimal(str(info.get("credits") or 3)), **kw}

        exp = s.get("expand")
        if exp:
            for code in _expand_codes(exp, bulletin):
                out.append(course_row(code, group_type="choose_credits",
                                      group_threshold=Decimal(str(exp["threshold"])),
                                      pool_seq=Decimal(str(exp["pool_seq"]))))
        c1 = s.get("choose_one")
        if c1:
            for code in c1["codes"]:
                out.append(course_row(code, group_type="choose_one",
                                      pair_group_id=Decimal(str(c1["pair"]))))
    return out


def _is_patch_row(row: dict) -> bool:
    gc = row.get("group_course", "")
    return gc.endswith(f"#{_LEVEL_KEY}") or "#__DEPT_CREDITS_" in gc


def level_pool_invented(spec: dict, rows: list[dict]) -> list[dict] | None:
    """The scraped rows `spec` replaces among a program's `rows`, or None when the
    spec no longer matches what is loaded (a re-scrape renumbered, repopulated or
    fixed it) — then nothing is touched.

    `replaces` mode: the whole pool at that pool_seq, which must hold only the
    expected codes. `invented` mode: rows with that code whose title matches the
    prose they were cut from, so a real course of the same code is never deleted.
    An empty result is fine once the patch's own rows are in place (idempotent)."""
    import re as _re
    group = [r for r in rows if r.get("requirement_group") == spec["group"]]
    if "replaces" in spec:
        rep = spec["replaces"]
        hit = [r for r in group
               if r.get("group_type") == "choose_credits" and not _is_patch_row(r)
               and r.get("pool_seq") is not None and int(r["pool_seq"]) == rep["pool_seq"]]
        if {r.get("course_code") for r in hit} - rep["codes"]:
            return None
    else:
        hit = [r for r in group if not _is_patch_row(r) and any(
               r.get("course_code") == code and _re.search(pat, str(r.get("course_title") or ""))
               for code, pat in spec["invented"])]
        if spec["invented"] and not hit and not any(_is_patch_row(r) for r in group):
            return None
        exp = spec.get("expand")
        if exp and any(int(r.get("pool_seq") or 0) != exp["pool_seq"]
                       or int(r.get("group_threshold") or 0) != exp["threshold"] for r in hit):
            return None            # the pool it sits in isn't the one this expands
    # A choose-one replaces any scraped row for one of its codes in this group
    # (e.g. a STAT 250 an alternatives patch inserted beside the STAT 200 row).
    c1 = spec.get("choose_one")
    if c1:
        ids = {id(r) for r in hit}
        hit += [r for r in group if r.get("course_code") in c1["codes"]
                and not _is_patch_row(r) and id(r) not in ids]
    return hit


def patch_level_pools():
    """Replace invented level-rule rows with real rules / course lists. Idempotent:
    once deleted there is nothing left to match, and put_item overwrites."""
    print("\nPatching level/subject pools (invented course codes from bulletin prose)...")
    deleted = written = 0
    cache: dict[str, list[dict]] = {}
    for spec in LEVEL_POOLS:
        prog = spec["program"]
        if prog not in cache:
            rows, kw = [], {"KeyConditionExpression": Key("program_name").eq(prog)}
            while True:
                resp = requirements_table.query(**kw)
                rows += resp.get("Items", [])
                if "LastEvaluatedKey" not in resp:
                    break
                kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            cache[prog] = rows
        rows = cache[prog]
        if not rows:
            print(f"  {prog}: not in catalog, skipped.")
            continue
        invented = level_pool_invented(spec, rows)
        if invented is None:
            print(f"  WARNING {prog} / '{spec['group']}': the scraped rows this patch replaces "
                  f"are not there; skipped (check the scrape).")
            continue
        for r in invented:
            requirements_table.delete_item(
                Key={"program_name": r["program_name"], "group_course": r["group_course"]})
            deleted += 1
        # Never add a list course the pool already has from the scrape.
        gone = {id(r) for r in invented}
        have = {(r.get("course_code"), str(r.get("pool_seq"))) for r in rows
                if r.get("requirement_group") == spec["group"] and not _is_patch_row(r)
                and id(r) not in gone}
        extra = {k: rows[0][k] for k in ("college", "degree") if rows[0].get(k)}
        for row in level_pool_rows(spec):
            if row["group_type"] == "choose_credits" and \
                    (row["course_code"], str(row["pool_seq"])) in have:
                continue
            requirements_table.put_item(Item={**row, **extra})
            written += 1
        cache[prog] = [r for r in rows if id(r) not in gone]
    print(f"  Deleted {deleted} invented rows, wrote {written} rows.")


def check_eti_requirements():
    """Check what requirement groups exist for ETI."""
    print(f"\nChecking ETI requirements in catalog...")
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(MAJOR),
        ProjectionExpression="requirement_group",
    )
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = requirements_table.query(
            KeyConditionExpression=Key("program_name").eq(MAJOR),
            ProjectionExpression="requirement_group",
            ExclusiveStartKey=resp["LastEvaluatedKey"]
        )
        items.extend(resp.get("Items", []))

    groups = sorted({i.get("requirement_group", "") for i in items})
    print(f"  Found {len(items)} rows across {len(groups)} requirement groups:")
    for g in groups:
        count = sum(1 for i in items if i.get("requirement_group") == g)
        print(f"    [{count:3d} rows] {g}")
    return len(items)

if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else None

    seed_user()

    if pdf_path:
        courses = seed_transcript_from_pdf(pdf_path)
    else:
        print("\nNo PDF provided — using hardcoded transcript data.")
        courses = seed_transcript_from_hardcoded()

    seed_courses(courses)

    patch_eti_catalog()
    patch_phys_alternatives()
    patch_known_alternatives()
    patch_choose_credits_option_groups()
    patch_adviser_defined_majors()
    patch_level_pools()

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from fix_junk_titles import fix_junk_titles
    fix_junk_titles()

    row_count = check_eti_requirements()
    if row_count == 0:
        print("\n  *** ETI program NOT found in catalog! Run load_catalog.py first. ***")
    else:
        print(f"\n  ETI program found with {row_count} requirement rows.")
        print(f"\nReady to audit. Run: curl -H 'x-user-id: {USER_ID}' http://localhost:8080/audit")
