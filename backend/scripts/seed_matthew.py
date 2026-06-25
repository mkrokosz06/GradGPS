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
    row_count = check_eti_requirements()
    if row_count == 0:
        print("\n  *** ETI program NOT found in catalog! Run load_catalog.py first. ***")
    else:
        print(f"\n  ETI program found with {row_count} requirement rows.")
        print(f"\nReady to audit. Run: curl -H 'x-user-id: {USER_ID}' http://localhost:8080/audit")
