"""Re-parse a user's stored transcript PDF with the CURRENT parser and rewrite
their transcript_courses rows — for when a parser fix changes what an existing
upload should have produced.  Mirrors the upload route's storage exactly
(delete-all then batch put).  The PDF, user record, and S3 object are untouched.

Usage (prod):
  AWS_PROFILE=gradgps DYNAMODB_ENDPOINT= S3_ENDPOINT= \
  AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= \
  python scripts/reparse_stored_transcript.py <user_id>
"""
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boto3.dynamodb.conditions import Key
from db import users_table, transcript_table, get_s3
from routers.transcript import S3_BUCKET
from transcript_parser import parse_and_detect


def main(user_id: str):
    user = users_table.get_item(Key={"user_id": user_id}).get("Item")
    if not user or not user.get("transcript_s3_key"):
        print(f"No stored transcript for {user_id}"); sys.exit(1)

    pdf = get_s3().get_object(Bucket=S3_BUCKET, Key=user["transcript_s3_key"])["Body"].read()
    courses, detection = parse_and_detect(pdf)
    print(f"{user_id}: re-parsed {len(courses)} courses "
          f"({'official' if detection.is_official else 'unofficial'})")
    if not courses:
        print("Parser returned no courses — refusing to wipe stored rows."); sys.exit(1)

    existing = []
    resp = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(user_id),
        ProjectionExpression="user_id, course_code",
    )
    existing.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.query(
            KeyConditionExpression=Key("user_id").eq(user_id),
            ProjectionExpression="user_id, course_code",
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        existing.extend(resp.get("Items", []))

    with transcript_table.batch_writer() as batch:
        for item in existing:
            batch.delete_item(Key={"user_id": item["user_id"], "course_code": item["course_code"]})
    with transcript_table.batch_writer() as batch:
        for c in courses:
            batch.put_item(Item={
                "user_id":        user_id,
                "course_code":    c["course_code"],
                "grade":          c.get("grade", ""),
                "credits_earned": Decimal(str(c.get("credits_earned", 0))),
                "term":           c.get("term", ""),
                "status":         c.get("status", "done"),
                "is_writing":     bool(c.get("is_writing")),
            })
    print(f"Replaced {len(existing)} stored rows with {len(courses)} re-parsed rows.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1])
