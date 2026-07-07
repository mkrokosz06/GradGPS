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
                "is_writing":     bool(c.get("is_writing")),
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


def patch_known_alternatives():
    """
    Fix choose-one alternative pairing defects across the entire catalog.

    The scraper inconsistently captured known interchangeable course alternatives as:
    both required in the same group (no pair), only one present (other absent), or
    both choose_one but without a pair_group_id linking them.

    Strategy per (program, group):
      - 2+ courses present + unpaired -> assign shared pair_group_id, set to choose_one
      - 1 course present + insert_missing=True -> insert absent alternatives, then pair
      - choose_credits pools -> skip (pairing doesn't apply to credit pools)
      - excluded combos -> skip (courses are genuinely both required there)
      - already paired -> skip (idempotent)

    One full table scan is performed upfront; all filtering happens in Python.

    Pair IDs:
      ETI pairs:        580-583
      PHYS 211/250:     600+
      MATH 250/251:     700+   (already applied, will be skipped as already-paired)
      This function:    800+
    """
    from collections import defaultdict

    print("\nPatching known course alternatives across all programs...")

    # ── Define all known alternative groups ───────────────────────────────────
    #
    # Each entry:
    #   codes         - list of course codes that are interchangeable (2 or 3)
    #   insert_missing - if True, insert absent alternatives when only 1 is present
    #   exclude        - fn(program_name, group_name) -> bool; True = skip this combo
    #
    # "MIXED" pairs (both sometimes required) use insert_missing=False and an
    # exclude function to protect programs where both courses are genuinely needed.

    GROUPS = [
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

    # Course info cache for insertion (title + credits from any existing row)
    course_info = {
        code: (rows[0].get("course_title", ""), rows[0].get("credits", Decimal("3")))
        for code, rows in rows_by_code.items() if rows
    }

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
        pair_id += 1
        total_patched += 1

    def insert_course(template_row, code):
        if code not in course_info or course_info[code][0] is None:
            return None
        title, credits = course_info[code]
        item = {k: v for k, v in template_row.items()}
        item["course_code"]  = code
        item["course_title"] = title
        item["credits"]      = credits
        item["group_course"] = f"{template_row['requirement_group']}#{code}"
        item.pop("pair_group_id", None)
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
                    nr = insert_course(template, mc)
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
    patch_known_alternatives()
    patch_choose_credits_option_groups()
    row_count = check_eti_requirements()
    if row_count == 0:
        print("\n  *** ETI program NOT found in catalog! Run load_catalog.py first. ***")
    else:
        print(f"\n  ETI program found with {row_count} requirement rows.")
        print(f"\nReady to audit. Run: curl -H 'x-user-id: {USER_ID}' http://localhost:8080/audit")
