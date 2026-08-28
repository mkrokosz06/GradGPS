"""
Transcript endpoints:
  POST /transcript/upload  — parse & store a PDF transcript
  GET  /transcript         — return stored transcript courses grouped by term
  DELETE /transcript       — delete all transcript courses and clear user record
"""

import os
import re
import asyncio
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request, Form, Query
from pydantic import BaseModel
from decimal import Decimal

from db import transcript_table, users_table, get_s3
from transcript_parser import (
    detect_kind, parse_with_detection, official_parse_looks_bad, _normalise_code,
)
from deps import get_user_id

router = APIRouter()
logger = logging.getLogger(__name__)

S3_BUCKET = os.getenv("S3_BUCKET", "degreecheck-transcripts")

# Upload hardening limits
MAX_UPLOAD_BYTES     = 5 * 1024 * 1024   # 5 MB — real transcripts are well under this
PDF_MAGIC            = b"%PDF-"           # every valid PDF begins with this
PARSE_TIMEOUT_SECONDS = 20                # bound worst-case parse time (PDF bombs)
_UPLOAD_CHUNK        = 64 * 1024

# Official-transcript consent gate. When on, a detected official transcript is
# blocked with a 409 until the client re-submits with acknowledge_official=true.
# When off (shadow mode), detection + the official parser still run and log, but
# never 409 — lets us validate the false-positive rate before the dialog goes
# live. NEVER auto-enabled; opt in via backend/.env. See CLAUDE.md.
OFFICIAL_DETECT = os.getenv("OFFICIAL_DETECT", "0") == "1"

_SEASON_ORDER  = {"SP": 0, "SU": 1, "FA": 2}
_SEASON_LABELS = {"SP": "Spring", "SU": "Summer", "FA": "Fall"}

# Manual course editing (add / swap / drop) is limited to in-progress rows — a
# student can change classes they're registered for but not rewrite graded
# history. See the "edit scope" decision in CLAUDE.md / the timeline docs.
_EDITABLE_STATUSES = {"in_progress"}
_TERM_RE = re.compile(r"^(FA|SP|SU) \d{4}$")
# DEPT NUMBER with an optional attribute-suffix letter (W/H/N/M/X/Y, e.g. IST 440W).
_COURSE_CODE_RE = re.compile(r"^[A-Z]{1,6} [0-9]{1,4}[A-Z]?$")
_MAX_COURSE_CREDITS = 12.0


def _clean_course_code(raw: str) -> tuple[str, bool]:
    """
    Normalise a user-entered course code to storage form and derive its
    writing-intensive flag, matching the transcript parser exactly:
      - collapse/upcase to canonical "DEPT NUMBER"
      - is_writing = a W/M/X/Y suffix on the number (captured before it's stripped)
      - course_code = base code with a trailing W/H/N attribute letter removed

    Returns (course_code, is_writing). Raises HTTPException(400) on a bad code.
    """
    code = re.sub(r"\s+", " ", (raw or "").strip().upper())
    if not _COURSE_CODE_RE.match(code):
        raise HTTPException(
            status_code=400,
            detail="Enter a course code like 'ETI 297' or 'IST 440W'.",
        )
    number = code.split(" ", 1)[1]
    is_writing = bool(re.search(r"[WMXY]$", number))
    return _normalise_code(code), is_writing


class CourseAdd(BaseModel):
    course_code:    str
    term:           str
    credits_earned: float = 3.0


class CourseSwap(BaseModel):
    original_code:  str
    course_code:    str
    credits_earned: float | None = None


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
                    "source":         c.get("source", "parsed"),
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

    # Defense in depth: this key must never traverse outside the user's prefix,
    # even if deps.get_user_id's charset enforcement ever changes.
    if "/" in user_id or ".." in user_id:
        raise HTTPException(status_code=400, detail="Invalid user id.")

    # 1. Delete the stored PDF FIRST. Our Privacy Policy promises that deleting a
    #    transcript removes the stored PDF, so if object storage is unreachable we
    #    must NOT report success. Fail loudly with the database left intact so the
    #    user can retry cleanly. delete_object is idempotent — it does not error
    #    when the key is already absent (e.g. no PDF was ever stored).
    try:
        get_s3().delete_object(Bucket=S3_BUCKET, Key=f"transcripts/{user_id}/transcript.pdf")
    except Exception:
        logger.exception("S3 transcript delete failed for user_id=%s", user_id)
        raise HTTPException(
            status_code=502,
            detail="Could not delete your stored transcript file. Please try again.",
        )

    # 2. Delete all course rows (paginated).
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

    # 3. Clear transcript metadata on the user record (including official-consent
    #    fields, so a later unofficial upload starts from a clean slate).
    users_table.update_item(
        Key={"user_id": user_id},
        UpdateExpression=(
            "REMOVE transcript_parsed_at, transcript_s3_key, "
            "transcript_kind, official_transcript_ack_at"
        ),
    )

    return {"status": "ok"}


@router.post("/upload")
async def upload_transcript(
    request: Request,
    file: UploadFile = File(...),
    acknowledge_official: bool = Form(False),
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

    # ── 1. Detect kind (cheap first pass — no parsing yet) ─────────────────────
    try:
        detection, pages_text = await asyncio.wait_for(
            asyncio.to_thread(detect_kind, pdf_bytes),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=422, detail="Transcript could not be processed in time. Please upload a standard PSU transcript PDF.")
    except Exception:
        logger.exception("Transcript detection failed for user_id=%s", user_id)
        raise HTTPException(status_code=422, detail="Could not read transcript. Make sure this is a PSU transcript PDF.")

    kind = "official" if detection.is_official else "unofficial"
    logger.info(
        "official_detection user=%s kind=%s score=%d signals=%s ack=%s",
        user_id, kind, detection.score, detection.signals, acknowledge_official,
    )

    # ── 1a. Official-transcript consent gate (before any parsing) ──────────────
    # In shadow mode (OFFICIAL_DETECT off) we skip the gate but still parse+store.
    if OFFICIAL_DETECT and detection.is_official and not acknowledge_official:
        raise HTTPException(status_code=409, detail={
            "code":             "official_transcript_detected",
            "needs_official_ack": True,
            "confidence":       detection.confidence,
            "signals":          detection.signals,
            "message":          "This looks like an official transcript. Confirm to proceed.",
        })

    # ── 1b. Parse with the matching parser (only now that we're proceeding) ────
    try:
        courses = await asyncio.wait_for(
            asyncio.to_thread(parse_with_detection, pdf_bytes, detection, pages_text),
            timeout=PARSE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=422, detail="Transcript could not be processed in time. Please upload a standard PSU transcript PDF.")
    except Exception:
        # Log the real error server-side; don't leak parser internals to the client.
        logger.exception("Transcript parse failed for user_id=%s", user_id)
        raise HTTPException(status_code=422, detail="Could not parse transcript. Make sure this is an unofficial PSU transcript PDF.")

    # ── 1c. Trustworthiness safety net (official parser is single-sample-tuned) ─
    # Refuse to store a garbled official parse; steer the user to the unofficial
    # transcript, which the app handles reliably.
    if detection.is_official and (not courses or official_parse_looks_bad(courses)):
        raise HTTPException(status_code=422, detail=(
            "We couldn't reliably read this official transcript's course list. "
            "Please upload your unofficial transcript from LionPATH instead "
            "(Student Center -> My Academics)."
        ))

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
        s3.put_object(
            Bucket=S3_BUCKET, Key=s3_key, Body=pdf_bytes,
            ContentType="application/pdf", Metadata={"transcript-kind": kind},
        )
    except Exception as e:
        logger.warning("S3 upload failed for %s: %s", s3_key, e)

    # ── 4. Update user's transcript metadata + official-consent audit trail ────
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    update_expr = "SET transcript_parsed_at = :ts, transcript_s3_key = :key, transcript_kind = :kind"
    expr_values = {":ts": now_iso, ":key": s3_key, ":kind": kind}
    if detection.is_official:
        # Records that the user was warned and consented to use an official transcript.
        update_expr += ", official_transcript_ack_at = :ack"
        expr_values[":ack"] = now_iso
    users_table.update_item(
        Key={"user_id": user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )

    result = {
        "status":         "ok",
        "courses_parsed": len(courses),
        "done":           sum(1 for c in courses if c["status"] == "done"),
        "in_progress":    sum(1 for c in courses if c["status"] == "in_progress"),
        "transfer":       sum(1 for c in courses if c["status"] == "transfer"),
        "transcript_kind": kind,
    }
    if detection.is_official:
        result["parse_warning"] = (
            "Official transcripts are parsed best-effort - please double-check your course list."
        )
    return result


# ── Manual course editing (in-progress / planned courses only) ─────────────────
# Lets a student swap, drop, or add a class they're registered for without
# re-uploading a whole transcript (e.g. switching a fall class over the summer).
# The audit and timeline read transcript_courses live, so an edit here flows
# through to every downstream view with no extra wiring. Graded/transfer history
# stays read-only — only status="in_progress" rows can be touched.

def _get_course(user_id: str, course_code: str) -> dict | None:
    resp = transcript_table.get_item(Key={"user_id": user_id, "course_code": course_code})
    return resp.get("Item")


def _course_view(item: dict) -> dict:
    """Client-facing shape, matching the rows GET /transcript returns."""
    return {
        "course_code":    item.get("course_code", ""),
        "grade":          item.get("grade", ""),
        "credits_earned": float(item.get("credits_earned", 0)),
        "status":         item.get("status", "in_progress"),
        "term":           item.get("term", ""),
        "source":         item.get("source", "parsed"),
    }


def _validate_credits(credits: float) -> Decimal:
    if credits is None or credits <= 0 or credits > _MAX_COURSE_CREDITS:
        raise HTTPException(
            status_code=400,
            detail=f"Credits must be between 0 and {int(_MAX_COURSE_CREDITS)}.",
        )
    return Decimal(str(credits))


@router.post("/course")
def add_course(body: CourseAdd, user_id: str = Depends(get_user_id)):
    """Add a class the student registered for (stored as in-progress + manual)."""
    course_code, is_writing = _clean_course_code(body.course_code)
    if not _TERM_RE.match((body.term or "").strip()):
        raise HTTPException(status_code=400, detail="Invalid term (expected e.g. 'FA 2026').")
    credits = _validate_credits(body.credits_earned)

    if _get_course(user_id, course_code) is not None:
        raise HTTPException(status_code=409, detail=f"{course_code} is already on your transcript.")

    item = {
        "user_id":        user_id,
        "course_code":    course_code,
        "grade":          "",
        "credits_earned": credits,
        "term":           body.term.strip(),
        "status":         "in_progress",
        "is_writing":     is_writing,
        "source":         "manual",
    }
    transcript_table.put_item(Item=item)
    return {"status": "ok", "course": _course_view(item)}


@router.patch("/course")
def swap_course(body: CourseSwap, user_id: str = Depends(get_user_id)):
    """Swap an in-progress class for another (optionally changing its credits)."""
    original_code, _ = _clean_course_code(body.original_code)
    existing = _get_course(user_id, original_code)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"{original_code} isn't on your transcript.")
    if existing.get("status") not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Only in-progress classes can be changed. Completed and transfer courses are read-only.",
        )

    new_code, is_writing = _clean_course_code(body.course_code)
    credits = (
        _validate_credits(body.credits_earned)
        if body.credits_earned is not None
        else Decimal(str(existing.get("credits_earned", 0)))
    )

    item = {
        "user_id":        user_id,
        "course_code":    new_code,
        "grade":          "",
        "credits_earned": credits,
        "term":           existing.get("term", ""),
        "status":         "in_progress",
        "is_writing":     is_writing,
        "source":         "manual",
    }

    if new_code != original_code:
        if _get_course(user_id, new_code) is not None:
            raise HTTPException(status_code=409, detail=f"{new_code} is already on your transcript.")
        transcript_table.delete_item(Key={"user_id": user_id, "course_code": original_code})
    transcript_table.put_item(Item=item)
    return {"status": "ok", "course": _course_view(item)}


@router.delete("/course")
def drop_course(course_code: str = Query(...), user_id: str = Depends(get_user_id)):
    """Drop an in-progress class from the transcript."""
    code, _ = _clean_course_code(course_code)
    existing = _get_course(user_id, code)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"{code} isn't on your transcript.")
    if existing.get("status") not in _EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Only in-progress classes can be dropped. Completed and transfer courses are read-only.",
        )
    transcript_table.delete_item(Key={"user_id": user_id, "course_code": code})
    return {"status": "ok", "course_code": code}
