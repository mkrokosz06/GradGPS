"""
POST /transcript/upload
Accepts a PDF, parses it, stores courses to DynamoDB, uploads PDF to S3.
"""

import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from decimal import Decimal

from db import transcript_table, users_table, get_s3
from transcript_parser import parse_transcript
from deps import get_user_id

router = APIRouter()

S3_BUCKET = os.getenv("S3_BUCKET", "degreecheck-transcripts")


@router.post("/upload")
async def upload_transcript(
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()

    # ── 1. Parse transcript ───────────────────────────────────────────────────
    try:
        courses = parse_transcript(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse transcript: {e}")

    if not courses:
        raise HTTPException(status_code=422, detail="No courses found in transcript. Make sure this is an unofficial PSU transcript PDF.")

    # ── 2. Store parsed courses to DynamoDB ───────────────────────────────────
    from boto3.dynamodb.conditions import Key as DKey
    # Paginate to ensure ALL existing courses are deleted, not just the first page.
    existing = []
    query_kwargs = {
        "KeyConditionExpression": DKey("user_id").eq(user_id),
        "ProjectionExpression": "user_id, course_code",
    }
    resp = transcript_table.query(**query_kwargs)
    existing.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.query(**query_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        existing.extend(resp.get("Items", []))

    if existing:
        with transcript_table.batch_writer() as batch:
            for item in existing:
                batch.delete_item(Key={"user_id": item["user_id"], "course_code": item["course_code"]})

    with transcript_table.batch_writer() as batch:
        for c in courses:
            item = {
                "user_id":        user_id,
                "course_code":    c["course_code"],
                "grade":          c.get("grade", ""),
                "credits_earned": Decimal(str(c.get("credits_earned", 0))),
                "term":           c.get("term", ""),
                "status":         c.get("status", "done"),
            }
            batch.put_item(Item=item)

    # ── 3. Upload raw PDF to S3 ───────────────────────────────────────────────
    s3_key = f"transcripts/{user_id}/transcript.pdf"
    try:
        s3 = get_s3()
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=pdf_bytes, ContentType="application/pdf")
    except Exception as e:
        print(f"S3 upload warning: {e}")

    # ── 4. Update user's transcript_parsed_at timestamp ───────────────────────
    from datetime import datetime, timezone
    users_table.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET transcript_parsed_at = :ts, transcript_s3_key = :key",
        ExpressionAttributeValues={
            ":ts":  datetime.now(timezone.utc).isoformat(),
            ":key": s3_key,
        },
    )

    return {
        "status":         "ok",
        "courses_parsed": len(courses),
        "done":           sum(1 for c in courses if c["status"] == "done"),
        "in_progress":    sum(1 for c in courses if c["status"] == "in_progress"),
        "transfer":       sum(1 for c in courses if c["status"] == "transfer"),
    }
