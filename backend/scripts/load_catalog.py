"""
Loads PSU_Major_Requirements.xlsx into the DynamoDB requirements table.
Safe to re-run — uses batch_writer which upserts (overwrites) existing items.

Refuses to load a spreadsheet whose junk-title rate exceeds 40% (the
signature of a broken scrape) unless --force is given; fix_junk_titles.py
repairs the residual junk after loading either way. The legacy 2025 xlsx
(scraped before the scrape_psu.py title fix) sits at 36.5%; files produced
by the fixed scraper should be in the single digits.

Usage:
    python scripts/load_catalog.py [--force]
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
        for num_col in ["group_threshold", "credits", "pair_group_id"]:
            val = clean(row.get(num_col, ""))
            if val is not None:
                item[num_col] = val

        # String optional fields
        if row.get("min_grade", "").strip():
            item["min_grade"] = row["min_grade"].strip()

        batch.put_item(Item=item)
        loaded += 1

        if loaded % 1000 == 0:
            print(f"  {loaded}/{total} rows loaded...")

print(f"\nDone. {loaded} rows written to DynamoDB requirements table.")
