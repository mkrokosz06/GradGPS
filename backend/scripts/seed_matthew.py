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
        {"course_code": "EDSGN 100", "grade": "A",  "credits_earned": 3.0, "term": "SU 2024", "status": "done"},
        {"course_code": "ENGL 15",   "grade": "B",  "credits_earned": 3.0, "term": "SU 2024", "status": "done"},
        # FA 2024
        {"course_code": "ANTH 140",  "grade": "B+", "credits_earned": 3.0, "term": "FA 2024", "status": "done"},
        {"course_code": "CHEM 110",  "grade": "D",  "credits_earned": 3.0, "term": "FA 2024", "status": "done"},
        {"course_code": "ECON 102",  "grade": "B-", "credits_earned": 3.0, "term": "FA 2024", "status": "done"},
        {"course_code": "ME 101",    "grade": "A",  "credits_earned": 1.0, "term": "FA 2024", "status": "done"},
        # SP 2025
        {"course_code": "CAS 100C",  "grade": "B+", "credits_earned": 3.0, "term": "SP 2025", "status": "done"},
        {"course_code": "GEOSC 40",  "grade": "A",  "credits_earned": 3.0, "term": "SP 2025", "status": "done"},
        {"course_code": "METEO 3",   "grade": "A-", "credits_earned": 3.0, "term": "SP 2025", "status": "done"},
        {"course_code": "MGMT 301",  "grade": "A-", "credits_earned": 3.0, "term": "SP 2025", "status": "done"},
        {"course_code": "SCM 200",   "grade": "B+", "credits_earned": 4.0, "term": "SP 2025", "status": "done"},
        # SU 2025
        {"course_code": "MATH 140",  "grade": "C",  "credits_earned": 4.0, "term": "SU 2025", "status": "done"},
        # FA 2025
        {"course_code": "ACCTG 211", "grade": "C",  "credits_earned": 4.0, "term": "FA 2025", "status": "done"},
        {"course_code": "ECON 104",  "grade": "C",  "credits_earned": 3.0, "term": "FA 2025", "status": "done"},
        {"course_code": "MKTG 301",  "grade": "C",  "credits_earned": 3.0, "term": "FA 2025", "status": "done"},
        {"course_code": "MUSIC 11",  "grade": "B+", "credits_earned": 3.0, "term": "FA 2025", "status": "done"},
        {"course_code": "THEA 101",  "grade": "B-", "credits_earned": 3.0, "term": "FA 2025", "status": "done"},
        # SP 2026 (in progress)
        {"course_code": "CAMS 45",   "grade": "",   "credits_earned": 0.0, "term": "SP 2026", "status": "in_progress"},
        {"course_code": "CMPSC 131", "grade": "",   "credits_earned": 0.0, "term": "SP 2026", "status": "in_progress"},
        {"course_code": "HM 208",    "grade": "",   "credits_earned": 0.0, "term": "SP 2026", "status": "in_progress"},
        {"course_code": "KINES 11",  "grade": "",   "credits_earned": 0.0, "term": "SP 2026", "status": "in_progress"},
        {"course_code": "SOC 119",   "grade": "",   "credits_earned": 0.0, "term": "SP 2026", "status": "in_progress"},
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
                "term":           c.get("term", ""),
                "status":         c.get("status", "done"),
            }
            batch.put_item(Item=item)

    done = sum(1 for c in courses if c["status"] == "done")
    ip   = sum(1 for c in courses if c["status"] == "in_progress")
    tr   = sum(1 for c in courses if c["status"] == "transfer")
    print(f"  Done: {done}  In-Progress: {ip}  Transfer: {tr}")

def patch_eti_catalog():
    """
    Fix two classes of catalog defects for the ETI program:

    1. Junk rows — the scraper captured credit counts ("3", "4") as course_title
       for some rows, creating duplicate entries that inflate the missing count.

    2. Missing pairs — BA-prefixed Smeal courses and their dept-prefix equivalents
       (MKTG 301, MGMT 301, FIN 301, BLAW 243) are choose-one alternatives but
       the scraper didn't capture their pair_group_id relationship.
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

    # Reload after deletions
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(MAJOR)
    )
    rows = resp.get("Items", [])

    # 2. Pair BA-prefix courses with their dept-prefix equivalents
    PAIRS = [
        ("BA 243",  "BLAW 243", Decimal("580")),  # Legal Environment
        ("BA 301",  "FIN 301",  Decimal("581")),  # Finance
        ("BA 303",  "MKTG 301", Decimal("582")),  # Marketing
        ("BA 304",  "MGMT 301", Decimal("583")),  # Management
    ]

    def unpaired_row(code):
        return next(
            (r for r in rows if r["course_code"] == code and not r.get("pair_group_id")),
            None,
        )

    paired = 0
    for code_a, code_b, pid in PAIRS:
        row_a, row_b = unpaired_row(code_a), unpaired_row(code_b)
        if not row_a or not row_b:
            continue
        for row in (row_a, row_b):
            requirements_table.update_item(
                Key={"program_name": row["program_name"], "group_course": row["group_course"]},
                UpdateExpression="SET pair_group_id = :pid, group_type = :gt",
                ExpressionAttributeValues={":pid": pid, ":gt": "choose_one"},
            )
        paired += 1
    print(f"  Fixed {paired} missing course pairs (BA<->dept-prefix equivalents).")


def patch_phys_alternatives():
    """
    Fix catalog defect: PHYS 211 (calc-based sequence) and PHYS 250 (algebra-based sequence)
    appear as both 'required' in the same requirement group for 39 program+group combos.
    In reality, programs offer these as alternatives (students on the MATH 22 track take
    PHYS 250; others take PHYS 211). This patches them to 'choose_one' pairs.

    Pair IDs start at 600 (ETI patches use 580-583).
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


def patch_math_alternatives():
    """
    Fix MATH 250/251 catalog defects. MATH 250 (3cr) and MATH 251 (4cr) cover the same
    differential equations content and are interchangeable for most programs. Four defects:

    1. Biological Engineering, B.S. — both listed as 'required' in same group (scraper bug).
       Fix: convert both to choose_one pair.

    2. Industrial Engineering, B.S. — only MATH 250 listed as 'required', MATH 251 absent.
       Fix: insert MATH 251 row + convert both to choose_one pair.

    3. Mining Engineering, B.S. — MATH 250 is orphaned choose_one (no pair_group_id),
       MATH 251 absent from "Requirements for the Major".
       Fix: insert MATH 251 + assign pair.

    4. Mathematics, Minor (Science) — both choose_one but no pair_group_id linking them.
       Fix: assign pair_group_id to both.

    Pair IDs start at 700 (ETI=580-583, PHYS=600+).
    """
    from boto3.dynamodb.conditions import Attr

    print("\nPatching MATH 250 / MATH 251 alternatives...")

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

    math250_rows = scan_code("MATH 250")
    math251_rows = scan_code("MATH 251")

    by_pg_250 = {(r["program_name"], r["requirement_group"]): r for r in math250_rows}
    by_pg_251 = {(r["program_name"], r["requirement_group"]): r for r in math251_rows}

    pair_id = Decimal("700")
    patched = 0

    def make_pair(row_250, row_251):
        nonlocal pair_id, patched
        for row in (row_250, row_251):
            requirements_table.update_item(
                Key={"program_name": row["program_name"], "group_course": row["group_course"]},
                UpdateExpression="SET pair_group_id = :pid, group_type = :gt",
                ExpressionAttributeValues={":pid": pair_id, ":gt": "choose_one"},
            )
        pair_id += 1
        patched += 1

    def insert_math251(template_row):
        """Insert a MATH 251 row cloned from a MATH 250 row."""
        group_course = f"{template_row['requirement_group']}#MATH 251"
        item = {k: v for k, v in template_row.items()}
        item["course_code"]  = "MATH 251"
        item["course_title"] = "Ordinary and Partial Differential Equations"
        item["credits"]      = Decimal("4")
        item["group_course"] = group_course
        item.pop("pair_group_id", None)
        requirements_table.put_item(Item=item)
        return item

    # 1. Biological Engineering — both required in same group → choose_one pair
    bio_key = ("Biological Engineering, B.S.", "Common Requirements for the Major (All Options)")
    if bio_key in by_pg_250 and bio_key in by_pg_251:
        make_pair(by_pg_250[bio_key], by_pg_251[bio_key])
        print("  Fixed Biological Engineering (both required → choose_one pair).")
    else:
        print("  Biological Engineering: rows not found — skipping.")

    # 2. Industrial Engineering — MATH 250 required, MATH 251 absent → insert + pair
    ie_key = ("Industrial Engineering, B.S. (Engineering)", "Common Requirements for the Major (All Options)")
    if ie_key in by_pg_250 and ie_key not in by_pg_251:
        new_row = insert_math251(by_pg_250[ie_key])
        make_pair(by_pg_250[ie_key], new_row)
        print("  Fixed Industrial Engineering (inserted MATH 251 + choose_one pair).")
    else:
        print("  Industrial Engineering: already fixed or rows not found — skipping.")

    # 3. Mining Engineering — MATH 250 orphaned choose_one, MATH 251 absent
    mining_key = ("Mining Engineering, B.S.", "Requirements for the Major")
    if mining_key in by_pg_250 and mining_key not in by_pg_251:
        new_row = insert_math251(by_pg_250[mining_key])
        make_pair(by_pg_250[mining_key], new_row)
        print("  Fixed Mining Engineering (inserted MATH 251 + choose_one pair).")
    else:
        print("  Mining Engineering: already fixed or rows not found — skipping.")

    # 4. Mathematics Minor — both choose_one but no pair_group_id
    minor_key = ("Mathematics, Minor (Science)", "Requirements for the Minor")
    if minor_key in by_pg_250 and minor_key in by_pg_251:
        r250, r251 = by_pg_250[minor_key], by_pg_251[minor_key]
        if not r250.get("pair_group_id") and not r251.get("pair_group_id"):
            make_pair(r250, r251)
            print("  Fixed Mathematics Minor (assigned pair_group_id to both choose_one rows).")
        else:
            print("  Mathematics Minor: already paired — skipping.")
    else:
        print("  Mathematics Minor: rows not found — skipping.")

    print(f"  Total: {patched} pairs fixed.")


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
    patch_math_alternatives()
    patch_choose_credits_option_groups()
    row_count = check_eti_requirements()
    if row_count == 0:
        print("\n  *** ETI program NOT found in catalog! Run load_catalog.py first. ***")
    else:
        print(f"\n  ETI program found with {row_count} requirement rows.")
        print(f"\nReady to audit. Run: curl -H 'x-user-id: {USER_ID}' http://localhost:8080/audit")
