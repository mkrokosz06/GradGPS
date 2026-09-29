"""
Remove the course alternatives `patch_known_alternatives()` inserted where the
bulletin never offers them, and rebuild the ones the bulletin states as a
compound branch. Verdicts come from program_data/alternative_inserts.json
(scripts/verify_alternative_inserts.py).

  drop   -> delete the inserted row; if its pair is left with one member, that
            member goes back to exactly what the scraper produced
  branch -> keep the inserted row and add the rest of the branch under a shared
            pair_branch_id: "ACCTG 211 or (ACCTG 201 and ACCTG 202)"
  keep   -> untouched

Every change is re-validated against the LIVE row before it is made: a row that
is missing, has gained a scrape sequence number, or sits in a different pair
than the verdict recorded is skipped, not guessed at. So the script is safe to
re-run, and safe against a catalog that has drifted since verification.

Before writing, every row it will delete or modify is saved to a backup file;
`--restore FILE` puts them all back and removes anything the run added.

Usage:
    python scripts/remove_unverified_alternatives.py              # dry run
    python scripts/remove_unverified_alternatives.py --apply
    python scripts/remove_unverified_alternatives.py --restore backups/alt_cleanup_<ts>.json
Against prod: see CLAUDE.md "Running seed/maintenance scripts against prod".
"""

import argparse
import copy
import datetime
import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERDICTS = os.path.join(BACKEND, "program_data", "alternative_inserts.json")
BULLETIN = os.path.join(BACKEND, "scripts", "bulletin_courses.json")


def _dec(v):
    return None if v is None else Decimal(str(v))


def plan(rows: list[dict], entries: list[dict], bulletin: dict) -> tuple[list[tuple], list[str]]:
    """The writes needed to bring `rows` (the live catalog rows of the affected
    programs) in line with `entries`. Pure: returns (ops, skipped-reasons).

    ops are ("delete", key) | ("update", key, set_fields, remove_fields) |
    ("put", item), with key = (program_name, group_course).
    """
    live = {(r["program_name"], r["group_course"]): r for r in rows}
    ops, skipped = [], []
    deleted: set[tuple] = set()

    def members(program, group, pid):
        return [r for r in rows if r["program_name"] == program
                and r.get("requirement_group") == group
                and r.get("pair_group_id") is not None
                and Decimal(str(r["pair_group_id"])) == pid]

    for e in entries:
        key = (e["program"], e["group_course"])
        row = live.get(key)
        pid = _dec(e["pair_group_id"])
        label = f"{e['program']} | {e['group']} | {e['inserted']}"
        if e["verdict"] == "keep":
            continue
        if row is None:
            if e["verdict"] == "drop":
                continue                     # already removed — idempotent
            skipped.append(f"missing row: {label}")
            continue
        if row.get("group_course") != f"{e['group']}#{e['inserted']}" or \
                row.get("pair_group_id") is None or Decimal(str(row["pair_group_id"])) != pid:
            skipped.append(f"row changed since verification: {label}")
            continue

        if e["verdict"] == "drop":
            ops.append(("delete", key))
            deleted.add(key)
            continue

        # branch: keep the inserted row, add the rest of the branch beside it.
        branch_id = f"alt-{pid}"
        if row.get("pair_branch_id") != branch_id:
            ops.append(("update", key, {"pair_branch_id": branch_id}, []))
        for code in e["branch"]:
            if code == e["inserted"]:
                continue
            mate_key = (e["program"], f"{e['group']}#{code}")
            if mate_key in live:
                continue
            info = bulletin.get(code)
            if not info:
                skipped.append(f"branch course not in bulletin: {code} ({label})")
                continue
            item = copy.deepcopy(row)
            item.update({"course_code": code, "course_title": info["title"],
                         "credits": Decimal(str(info["credits"])),
                         "group_course": mate_key[1], "pair_branch_id": branch_id})
            ops.append(("put", item))

    # A pair left with ONE member reads as individually required — which is
    # what the scraper said before the insert. Put that row back exactly.
    by_pair: dict[tuple, list[dict]] = {}
    for e in entries:
        if e["verdict"] == "drop" and (e["program"], e["group_course"]) in deleted:
            by_pair.setdefault((e["program"], e["group"], _dec(e["pair_group_id"])), []).append(e)
    for (program, group, pid), drops in by_pair.items():
        left = [r for r in members(program, group, pid)
                if (program, r["group_course"]) not in deleted]
        if len(left) != 1:
            continue                         # still a real pair (a 3-way group), or nothing left
        mate = left[0]
        if mate["course_code"] not in drops[0]["partners"] or \
                mate["group_course"] == f"{group}#{mate['course_code']}":
            skipped.append(f"partner is not the scraped row: {program} | {group} | {mate['course_code']}")
            continue
        if mate.get("group_type") != "choose_one":
            skipped.append(f"partner re-typed since the patch: {program} | {group} | {mate['course_code']}")
            continue
        # The patch only ever inserted beside an UNPAIRED course, so before the
        # insert this row stood alone — individually required, which is what a
        # lone row means to the audit whether typed required or choose_one.
        # Restoring from the scrape file instead is wrong: pair ids are numbered
        # per scrape run, and the local xlsx is not the run prod was loaded from
        # (its pair 409 is CAS 100 / CAS 138T in the loaded catalog).
        ops.append(("update", (program, mate["group_course"]),
                    {"group_type": "required"}, ["pair_group_id"]))

    return ops, skipped


def _query_program(table, program: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key
    rows, kw = [], {"KeyConditionExpression": Key("program_name").eq(program)}
    while True:
        r = table.query(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            return rows
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def apply(ops: list[tuple], table, rows: list[dict], backup_path: str) -> None:
    live = {(r["program_name"], r["group_course"]): r for r in rows}
    before = []
    for op in ops:
        if op[0] in ("delete", "update"):
            before.append(live[op[1]])
    added = [[op[1]["program_name"], op[1]["group_course"]] for op in ops if op[0] == "put"]
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    with open(backup_path, "w", encoding="utf-8") as fh:
        json.dump({"before": before, "added": added}, fh, default=_encode, indent=1)

    for op in ops:
        if op[0] == "delete":
            table.delete_item(Key={"program_name": op[1][0], "group_course": op[1][1]})
        elif op[0] == "put":
            table.put_item(Item=op[1])
        else:
            _, key, set_fields, remove = op
            expr, values, names = [], {}, {}
            for i, (k, v) in enumerate(set_fields.items()):
                names[f"#s{i}"] = k
                values[f":s{i}"] = v
                expr.append(f"#s{i} = :s{i}")
            update = ("SET " + ", ".join(expr)) if expr else ""
            if remove:
                for i, k in enumerate(remove):
                    names[f"#r{i}"] = k
                update += (" " if update else "") + "REMOVE " + ", ".join(f"#r{i}" for i in range(len(remove)))
            kw = {"Key": {"program_name": key[0], "group_course": key[1]},
                  "UpdateExpression": update, "ExpressionAttributeNames": names}
            if values:
                kw["ExpressionAttributeValues"] = values
            table.update_item(**kw)


def _encode(v):
    """DynamoDB numbers are Decimals; tag them so a restore writes them back as
    numbers, byte-for-byte, rather than as strings."""
    if isinstance(v, Decimal):
        return {"__decimal__": str(v)}
    raise TypeError(f"not JSON serialisable: {type(v).__name__}")


def _decode(obj):
    return Decimal(obj["__decimal__"]) if set(obj) == {"__decimal__"} else obj


def restore(table, backup_path: str) -> None:
    data = json.load(open(backup_path, encoding="utf-8"), object_hook=_decode)
    for item in data["before"]:
        table.put_item(Item=item)
    for program, group_course in data["added"]:
        table.delete_item(Key={"program_name": program, "group_course": group_course})
    print(f"Restored {len(data['before'])} rows, removed {len(data['added'])} added rows.")


def main():
    from db import requirements_table
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore")
    args = ap.parse_args()

    if args.restore:
        restore(requirements_table, args.restore)
        return

    entries = json.load(open(VERDICTS, encoding="utf-8"))["entries"]
    bulletin = json.load(open(BULLETIN, encoding="utf-8"))
    rows = []
    for program in sorted({e["program"] for e in entries if e["verdict"] != "keep"}):
        rows += _query_program(requirements_table, program)

    ops, skipped = plan(rows, entries, bulletin)
    kinds = {k: sum(1 for o in ops if o[0] == k) for k in ("delete", "update", "put")}
    print(f"Plan: {kinds}")
    for s in skipped:
        print("  SKIP", s)
    if not args.apply:
        print("Dry run — nothing written. Re-run with --apply.")
        return
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKEND, "backups", f"alt_cleanup_{stamp}.json")
    apply(ops, requirements_table, rows, backup)
    print(f"Applied. Backup: {backup}")


if __name__ == "__main__":
    main()
