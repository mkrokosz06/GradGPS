"""
Backfill `course_title` + `credits` (attempted) onto already-stored transcript
courses.

Older uploads were parsed before the transcript parser captured course titles and
attempted credits, so their rows carry neither — which is why timeline/home cards
show no title next to the code and in-progress classes show no credit count.

This re-parses each user's stored S3 PDF and **enriches the existing rows in
place** (matched by course_code), rather than the delete-and-rewrite the upload
route does. That deliberately preserves manual add/swap/drop edits and each row's
stored term; a row is only touched to add the two missing display fields.

Usage:
    python scripts/backfill_course_titles.py [--dry-run] [--user USER_ID]

Against prod (SSO; blank AWS vars beat .env — see CLAUDE.md):
    AWS_PROFILE=gradgps DYNAMODB_ENDPOINT= S3_ENDPOINT= AWS_ACCESS_KEY_ID= \
      AWS_SECRET_ACCESS_KEY= python scripts/backfill_course_titles.py --dry-run
"""
import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boto3.dynamodb.conditions import Key

from db import transcript_table, get_s3
from transcript_parser import parse_and_detect

S3_BUCKET = os.getenv("S3_BUCKET", "degreecheck-transcripts")


def _all_user_ids() -> list[str]:
    """Distinct user_ids present in the transcript_courses table."""
    users: set[str] = set()
    resp = transcript_table.scan(ProjectionExpression="user_id")
    for it in resp.get("Items", []):
        users.add(it["user_id"])
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.scan(
            ProjectionExpression="user_id", ExclusiveStartKey=resp["LastEvaluatedKey"]
        )
        for it in resp.get("Items", []):
            users.add(it["user_id"])
    return sorted(users)


def _parsed_map(user_id: str) -> dict[str, dict] | None:
    """code -> {title, attempted} from the user's stored PDF, or None if no PDF."""
    key = f"transcripts/{user_id}/transcript.pdf"
    try:
        obj = get_s3().get_object(Bucket=S3_BUCKET, Key=key)
        pdf_bytes = obj["Body"].read()
    except Exception:
        return None
    courses, _ = parse_and_detect(pdf_bytes)
    return {
        c["course_code"]: {
            "title": c.get("course_title", ""),
            "attempted": float(c.get("credits", c.get("credits_earned", 0)) or 0),
        }
        for c in courses
    }


def backfill_user(user_id: str, dry_run: bool) -> tuple[int, int]:
    """Returns (rows_examined, rows_updated) for one user."""
    pmap = _parsed_map(user_id)
    if pmap is None:
        print(f"  {user_id}: no stored PDF — skipped")
        return 0, 0

    resp = transcript_table.query(KeyConditionExpression=Key("user_id").eq(user_id))
    rows = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        rows.extend(resp.get("Items", []))

    updated = 0
    for r in rows:
        code = r.get("course_code", "")
        # Only enrich rows that (a) match a parsed course and (b) are still missing
        # the fields. Manual rows (source="manual") aren't in the parse → left alone.
        if code not in pmap:
            continue
        has_title = bool(str(r.get("course_title", "")).strip())
        has_credits = r.get("credits") is not None
        if has_title and has_credits:
            continue
        info = pmap[code]
        if dry_run:
            print(f"    would set {code}: title={info['title']!r} credits={info['attempted']}")
            updated += 1
            continue
        transcript_table.update_item(
            Key={"user_id": user_id, "course_code": code},
            UpdateExpression="SET course_title = :t, credits = :c",
            ExpressionAttributeValues={
                ":t": info["title"],
                ":c": Decimal(str(info["attempted"])),
            },
        )
        updated += 1
    print(f"  {user_id}: {updated} of {len(rows)} rows enriched")
    return len(rows), updated


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report changes without writing")
    ap.add_argument("--user", help="backfill a single user_id (default: all)")
    args = ap.parse_args()

    user_ids = [args.user] if args.user else _all_user_ids()
    print(f"Backfilling {len(user_ids)} user(s){' (dry run)' if args.dry_run else ''}...")

    total_rows = total_updated = 0
    for uid in user_ids:
        er, up = backfill_user(uid, args.dry_run)
        total_rows += er
        total_updated += up

    verb = "would update" if args.dry_run else "updated"
    print(f"\nDone. {verb} {total_updated} row(s) across {len(user_ids)} user(s).")


if __name__ == "__main__":
    main()
