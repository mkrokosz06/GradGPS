"""
Loads PSU_Major_Requirements.xlsx into the DynamoDB requirements table.
Safe to re-run — uses batch_writer which upserts (overwrites) existing items.

--replace clears the old catalog first, and a re-load into a table that already
holds one NEEDS it.  The sort key is `group#code#idx` where idx is the row's
position in the spreadsheet, so a scrape that adds or removes any row shifts
almost every index after it.  Those shifted keys don't overwrite the old items,
they sit beside them: without --replace, re-loading a 34k-row file over a 32k-row
catalog leaves ~66k rows and every program carrying two copies of itself.
Sentinel rows (program_name starting "__": __GEN_ED__, __CROSSLISTINGS__) are
never touched — they are written by other scripts and must survive a reload.

A fresh local DB (docker restart → setup_tables) has nothing to clear, which is
why the flag is opt-in; a production reload is the case that requires it.

Refuses to load a spreadsheet whose junk-title rate exceeds 40% (the
signature of a broken scrape) unless --force is given; fix_junk_titles.py
repairs the residual junk after loading either way. The legacy 2025 xlsx
(scraped before the scrape_psu.py title fix) sits at 36.5%; files produced
by the fixed scraper should be in the single digits.

Usage:
    python scripts/load_catalog.py [--force] [--replace]
"""

import sys, os, math
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import boto3
import pandas as pd
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()

EXCEL_PATH = os.path.join(os.path.dirname(__file__), "../../PSU_Major_Requirements.xlsx")

dynamo_url = os.getenv("DYNAMODB_ENDPOINT")
region     = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

kwargs = dict(region_name=region)
if dynamo_url:
    kwargs["endpoint_url"] = dynamo_url

dynamodb = boto3.resource("dynamodb", **kwargs)
table    = dynamodb.Table("requirements")

print(f"Loading: {EXCEL_PATH}")
df = pd.read_excel(EXCEL_PATH, sheet_name="All Requirements", dtype=str)
df = df.fillna("")

total = len(df)
print(f"Rows to load: {total}")

# ── Junk-title guardrail ──────────────────────────────────────────────────────
from fix_junk_titles import _is_junk

junk_count = int(df["course_title"].map(_is_junk).sum())
junk_pct = 100 * junk_count / max(total, 1)
if junk_count:
    print(f"WARNING: {junk_count} rows ({junk_pct:.1f}%) have junk course titles "
          f"(credit values scraped as titles). fix_junk_titles.py repairs these post-load.")
if junk_pct > 40 and "--force" not in sys.argv:
    sys.exit("ABORTING: junk-title rate exceeds 40% — this looks like a broken scrape. "
             "Re-run scrape_psu.py (title misparse was fixed) or pass --force to load anyway.")

def clean(val):
    """Convert pandas value to a DynamoDB-safe type."""
    if val == "" or val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f):
            return None
        # DynamoDB requires Decimal for numbers
        return Decimal(str(val))
    except (ValueError, TypeError):
        return str(val)

# ── Optional: clear the existing catalog first ───────────────────────────────
def clear_catalog():
    """Delete every non-sentinel row from the requirements table.

    Scans for keys only (the projection keeps the scan cheap) and deletes in
    batches.  A row whose program_name starts with "__" is a sentinel written by
    another script — __GEN_ED__ (rebuild_gen_ed.py) and __CROSSLISTINGS__
    (monthly_refresh.py) — and is skipped, so a catalog reload never destroys
    gen-ed requirements or the cross-listing pairs.
    """
    print("\n--replace: clearing the existing catalog...")
    keys, kept = [], 0
    scan_kw = dict(ProjectionExpression="program_name, group_course")
    resp = table.scan(**scan_kw)
    while True:
        for it in resp.get("Items", []):
            if str(it.get("program_name", "")).startswith("__"):
                kept += 1
                continue
            keys.append({"program_name": it["program_name"],
                         "group_course": it["group_course"]})
        if "LastEvaluatedKey" not in resp:
            break
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **scan_kw)

    print(f"  {len(keys)} catalog rows to delete, {kept} sentinel rows preserved")
    deleted = 0
    with table.batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key=k)
            deleted += 1
            if deleted % 5000 == 0:
                print(f"  {deleted}/{len(keys)} deleted...")
    print(f"  Cleared {deleted} rows.\n")


if "--replace" in sys.argv:
    clear_catalog()

loaded = 0
with table.batch_writer() as batch:
    for idx, row in df.iterrows():
        program  = str(row["program_name"]).strip()
        group    = str(row["requirement_group"]).strip()
        code     = str(row["course_code"]).strip()

        if not program or not code:
            continue

        # Sort key includes the row index so duplicate course/group combos (e.g. PHYS 211
        # appearing twice in the same section) never collide on the composite key.
        group_course = f"{group}#{code}#{idx}"

        item = {
            "program_name":      program,
            "group_course":      group_course,
            "requirement_group": group,
            "group_type":        str(row.get("group_type", "required")).strip() or "required",
            "course_code":       code,
            "course_title":      str(row.get("course_title", "")).strip(),
            "college":           str(row.get("college", "")).strip(),
            "degree":            str(row.get("degree", "")).strip(),
        }

        # Numeric fields — only include if present
        # pool_seq distinguishes the several independent pools a single
        # requirement section can hold ("Select 3 credits from..." three times
        # over). Dropping it re-merges them into one, which is the bug this
        # column exists to fix.
        for num_col in ["group_threshold", "credits", "pair_group_id", "pool_seq"]:
            val = clean(row.get(num_col, ""))
            if val is not None:
                item[num_col] = val

        # String optional fields
        if row.get("min_grade", "").strip():
            item["min_grade"] = row["min_grade"].strip()

        # pair_branch_id marks the members of a compound choose-one branch
        # ("ACCTG 211 or (ACCTG 201 and ACCTG 202)"). It is a STRING, so it can't
        # ride along in the numeric loop above — and dropping it would silently
        # flatten the branch back into "any one of these will do".
        branch = row.get("pair_branch_id", "")
        if isinstance(branch, str) and branch.strip():
            item["pair_branch_id"] = branch.strip()

        batch.put_item(Item=item)
        loaded += 1

        if loaded % 1000 == 0:
            print(f"  {loaded}/{total} rows loaded...")

print(f"\nDone. {loaded} rows written to DynamoDB requirements table.")
