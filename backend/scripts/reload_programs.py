"""
Re-scrape and replace the catalog rows of SPECIFIC programs, leaving every other
program untouched.

A full reload (`load_catalog.py --replace`) rewrites all ~35k rows and must
re-run every patch script in the same pass or ~629 injected alternatives vanish
(CLAUDE.md, "A re-scrape is safe; a re-load is not"). When a scraper fix only
changes some programs, this swaps just those:

  1. scrape each listed program with the current scrape_psu.py
  2. build items exactly as load_catalog.py does, with pair ids / branch ids
     offset above the table's current maximum, so a new pair can never share an
     id with an existing one
  3. back up every existing row of those programs, delete them, write the new ones
  4. run the standard patch pipeline (apply_catalog_patches.py) in the same pass

Dry run by default. `--restore FILE` puts the backed-up rows back and removes
what the reload wrote.

Usage:
    python scripts/reload_programs.py --programs programs.json [--cache DIR]
    python scripts/reload_programs.py --programs programs.json --apply
    python scripts/reload_programs.py --restore backups/reload_<ts>.json
Against prod: see CLAUDE.md "Running seed/maintenance scripts against prod".
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

XLSX_PATH = os.path.join(os.path.dirname(BACKEND), "PSU_Major_Requirements.xlsx")


def _num(val):
    if val in (None, "", "None"):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:                                   # NaN
        return None
    return Decimal(str(val))


def build_items(rows: list[dict], id_base: int) -> list[dict]:
    """Scraped rows -> DynamoDB items, as load_catalog.py builds them.

    Pair ids from the scraper are a per-run counter starting at 1; `id_base`
    lifts them above every id already in the table. Branch ids ("b17") move
    with them."""
    items = []
    for i, row in enumerate(rows):
        program = str(row["program_name"]).strip()
        group = str(row["requirement_group"]).strip()
        code = str(row["course_code"]).strip()
        if not program or not code:
            continue
        item = {
            "program_name":      program,
            "group_course":      f"{group}#{code}#{i}",
            "requirement_group": group,
            "group_type":        str(row.get("group_type") or "required").strip() or "required",
            "course_code":       code,
            "course_title":      str(row.get("course_title") or "").strip(),
            "college":           str(row.get("college") or "").strip(),
            "degree":            str(row.get("degree") or "").strip(),
        }
        for col in ("group_threshold", "credits", "pool_seq"):
            v = _num(row.get(col))
            if v is not None:
                item[col] = v
        pid = _num(row.get("pair_group_id"))
        if pid is not None:
            item["pair_group_id"] = pid + id_base
        if str(row.get("focus_area") or "").strip():
            item["focus_area"] = str(row["focus_area"]).strip()
        if str(row.get("min_grade") or "").strip():
            item["min_grade"] = str(row["min_grade"]).strip()
        branch = str(row.get("pair_branch_id") or "").strip()
        if branch:
            m = re.fullmatch(r"b(\d+)", branch)
            item["pair_branch_id"] = f"b{int(m.group(1)) + id_base}" if m else branch
        items.append(item)
    return items


def _encode(v):
    if isinstance(v, Decimal):
        return {"__decimal__": str(v)}
    raise TypeError(type(v).__name__)


def _decode(obj):
    return Decimal(obj["__decimal__"]) if set(obj) == {"__decimal__"} else obj


def _query(table, program):
    from boto3.dynamodb.conditions import Key
    rows, kw = [], {"KeyConditionExpression": Key("program_name").eq(program)}
    while True:
        r = table.query(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            return rows
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def _max_pair_id(table) -> int:
    top, kw = 0, {"ProjectionExpression": "pair_group_id, pair_branch_id"}
    while True:
        r = table.scan(**kw)
        for it in r["Items"]:
            if it.get("pair_group_id") is not None:
                top = max(top, int(it["pair_group_id"]))
            m = re.fullmatch(r"b(\d+)", str(it.get("pair_branch_id") or ""))
            if m:
                top = max(top, int(m.group(1)))
        if "LastEvaluatedKey" not in r:
            return top
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def restore(table, path):
    data = json.load(open(path, encoding="utf-8"), object_hook=_decode)
    for program in data["programs"]:
        with table.batch_writer() as batch:
            for it in _query(table, program):
                batch.delete_item(Key={"program_name": it["program_name"],
                                       "group_course": it["group_course"]})
    with table.batch_writer() as batch:
        for it in data["before"]:
            batch.put_item(Item=it)
    print(f"Restored {len(data['before'])} rows across {len(data['programs'])} programs.")


def main():
    import pandas as pd
    import scrape_psu
    from db import requirements_table as table

    ap = argparse.ArgumentParser()
    ap.add_argument("--programs", help="JSON list of program names")
    ap.add_argument("--cache", help="directory of cached bulletin pages (read-through)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore")
    args = ap.parse_args()

    if args.restore:
        restore(table, args.restore)
        return

    if args.cache:
        from bs4 import BeautifulSoup
        import requests

        def cached_soup(url, retries=3):
            path = os.path.join(args.cache, re.sub(r"[^a-z0-9]+", "_", url.lower())[-120:] + ".html")
            if not os.path.exists(path):
                os.makedirs(args.cache, exist_ok=True)
                html = requests.get(url, headers=scrape_psu.HEADERS, timeout=30).text
                open(path, "w", encoding="utf-8").write(html)
                time.sleep(1)
            return BeautifulSoup(open(path, encoding="utf-8").read(), "lxml")
        scrape_psu.get_soup = cached_soup

    programs = json.load(open(args.programs, encoding="utf-8"))
    x = pd.read_excel(XLSX_PATH)
    meta = {r.program_name: (r.url, str(r.college)) for r in x.itertuples()}

    id_base = _max_pair_id(table) + 1000
    before, new_items, skipped = [], [], []
    for p in programs:
        if p not in meta:
            skipped.append(f"{p}: no URL on record")
            continue
        url, college = meta[p]
        rows, _ = scrape_psu.scrape_program_requirements({"url": url, "name": p, "college": college})
        names = {r["program_name"] for r in rows}
        if names != {p}:
            skipped.append(f"{p}: page now titled {sorted(names)[:2]}")
            continue
        existing = _query(table, p)
        if not existing:
            skipped.append(f"{p}: no rows in the table")
            continue
        items = build_items(rows, id_base)
        id_base = max([id_base] + [int(i["pair_group_id"]) for i in items if "pair_group_id" in i]) + 1
        before += existing
        new_items += items

    done = sorted({i["program_name"] for i in new_items})
    print(f"Plan: replace {len(before)} rows with {len(new_items)} across {len(done)} programs")
    for s in skipped:
        print("  SKIP", s)
    if not args.apply:
        print("Dry run - nothing written. Re-run with --apply.")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKEND, "backups", f"reload_{stamp}.json")
    os.makedirs(os.path.dirname(backup), exist_ok=True)
    json.dump({"programs": done, "before": before}, open(backup, "w", encoding="utf-8"),
              default=_encode, indent=1)
    with table.batch_writer() as batch:
        for it in before:
            batch.delete_item(Key={"program_name": it["program_name"],
                                   "group_course": it["group_course"]})
    with table.batch_writer() as batch:
        for it in new_items:
            batch.put_item(Item=it)
    print(f"Replaced. Backup: {backup}")

    # The same pass as the load, per CLAUDE.md: without it the verified
    # alternatives and pairings these programs carried are gone.
    from seed_matthew import (patch_eti_catalog, patch_phys_alternatives,
                              patch_known_alternatives, patch_choose_credits_option_groups)
    from fix_junk_titles import fix_junk_titles
    patch_eti_catalog()
    patch_phys_alternatives()
    patch_known_alternatives()
    patch_choose_credits_option_groups()
    fix_junk_titles()
    print("Patches applied.")


if __name__ == "__main__":
    main()
