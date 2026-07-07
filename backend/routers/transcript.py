"""
Transcript endpoints:
  POST /transcript/upload  — parse & store a PDF transcript
  GET  /transcript         — return stored transcript courses grouped by term
  DELETE /transcript       — delete all transcript courses and clear user record
"""

import os
import asyncio
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from decimal import Decimal

from db import transcript_table, users_table, get_s3
from transcript_parser import parse_transcript
from deps import get_user_id

router = APIRouter()
logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "degreecheck-transcripts")

# Upload hardening limits
MAX_UPLOAD_BYTES     = 5 * 1024 * 1024   # 5 MB — real transcripts are well under this
PDF_MAGIC            = b"%PDF-"           # every valid PDF begins with this
PARSE_TIMEOUT_SECONDS = 20                # bound worst-case parse time (PDF bombs)
_UPLOAD_CHUNK        = 64 * 1024

_SEASON_ORDER  = {"SP": 0, "SU": 1, "FA": 2}
_SEASON_LABELS = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}


def _term_key(term: str) -> tuple:
    parts = term.split()
    if len(parts) != 2:
        return (9999, 99)
    return (int(parts[1]), _SEASON_ORDER.get(parts[0], 99))


def _term_label(term: str) -> str:
    parts = term.split()
    if len(parts) != 2:
        return term
    return f"{_SEASON_LABELS.get(parts[0], parts[0])} {parts[1]}"


@router.get("")
def get_transcript(user_id: str = Depends(get_user_id)):
    """Return the user's stored transcript courses grouped by term."""
    from boto3.dynamodb.conditions import Key as DKey

    resp = transcript_table.query(KeyConditionExpression=DKey("user_id").eq(user_id))
    courses = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.query(
            KeyConditionExpression=DKey("user_id").eq(user_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        courses.extend(resp.get("Items", []))

    if not courses:
        return {"has_transcript": False, "courses_total": 0, "terms": []}

    # Group by term; transfer credits get their own bucket
    transfer = [c for c in courses if c.get("status") == "transfer"]
    regular  = [c for c in courses if c.get("status") != "transfer"]

    term_map: dict[str, list] = {}
    for c in regular:
        t = c.get("term") or "Unknown"
        term_map.setdefault(t, []).append(c)

    sorted_terms = sorted(term_map.keys(), key=_term_key)

    terms = []
    if transfer:
        terms.append({
            "term":  "Transfer",
            "label": "Transfer Credits",
            "courses": [
                {
                    "course_code":    c.get("course_code", ""),
                    "grade":          "TR",
                    "credits_earned": float(c.get("credits_earned", 0)),
                    "status":         "transfer",
                }
                for c in transfer
            ],
        })

    for t in sorted_terms:
        terms.append({
            "term":  t,
            "label": _term_label(t),
            "courses": [
                {
                    "course_code":    c.get("course_code", ""),
                    "grade":          c.get("grade", ""),
                    "credits_earned": float(c.get("credits_earned", 0)),
                    "status":         c.get("status", "done"),
                }
                for c in term_map[t]
            ],
        })

    return {
        "has_transcript": True,
        "courses_total":  len(courses),
        "terms":          terms,
    }


@router.delete("")
def delete_transcript(user_id: str = Depends(get_user_id)):
    """Delete all transcript courses for the user and clear their transcript metadata."""
    from boto3.dynamodb.conditions import Key as DKey

    # Paginate and delete all courses
    query_kwargs = {
        "KeyConditionExpression": DKey("user_id").eq(user_id),
        "ProjectionExpression": "user_id, course_code",
    }
    resp = transcript_table.query(**query_kwargs)
    existing = list(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = transcript_table.query(**query_kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        existing.extend(resp.get("Items", []))

    if existing:
        with transcript_table.batch_writer() as batch:
            for item in existing:
                batch.delete_item(Key={"user_id": item["user_id"], "course_code": item["course_code"]})

    # Clear transcript metadata on the user record
    users_table.update_item(
        Key={"user_id": user_id},
        UpdateExpression="REMOVE transcript_parsed_at, transcript_s3_key",
    )

    # Best-effort S3 delete
    try:
        s3 = get_s3()
        s3.delete_object(Bucket=S3_BUCKET, Key=f"transcripts/{user_id}/transcript.pdf")
    except Exception:
        pass

    return {"status": "ok"}


@router.post("/upload")
async def upload_transcript(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
):
    # ── 0. Validate the upload before touching the parser ─────────────────────
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Fast reject on the declared body size (an upper bound; may be absent/wrong).
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="File too large. Maximum size is 5 MB.")
        except ValueError:
            pass  # unparseable header — fall through to the hard cap below

    # Read with a hard cap; Content-Length can lie or be omitted, so this is the
    # real enforcement. Stop the moment we exceed the limit instead of buffering
    # the whole (potentially huge) body into memory.
    pdf_bytes = bytearray()
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        pdf_bytes.extend(chunk)
        if len(pdf_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large. Maximum size is 5 MB.")
    pdf_bytes = bytes(pdf_bytes)

    # Verify the real content is a PDF, not just a .pdf-named blob.
    if not pdf_bytes.startswith(PDF_MAGIC):
        raise HTTPException(status_code=400, detail="File is not a valid PDF.")

    # ── 1. Parse transcript (off the event loop, with a wall-clock bound) ──────
    try:
        courses = await asyncio.wait_for(
            asyncio.to_thread(parse_transcript, pdf_bytes),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=422, detail="Transcript could not be processed in time. Please upload a standard PSU transcript PDF.")
    except Exception:
        # Log the real error server-side; don't leak parser internals to the client.
        logger.exception("Transcript parse failed for user_id=%s", user_id)
        raise HTTPException(status_code=422, detail="Could not parse transcript. Make sure this is an unofficial PSU transcript PDF.")

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
                "is_writing":     bool(c.get("is_writing")),
            }
            batch.put_item(Item=item)

    # ── 3. Upload raw PDF to S3 ───────────────────────────────────────────────
    # user_id charset is enforced in deps.get_user_id; re-check here anyway so
    # this key can never traverse outside its prefix even if deps changes.
    if "/" in user_id or ".." in user_id:
        raise HTTPException(status_code=400, detail="Invalid user id.")
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
