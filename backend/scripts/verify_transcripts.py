"""Verify every stored transcript: re-parse the S3 PDF with the CURRENT parser,
diff against the stored transcript_courses rows, and run integrity checks.
Read-only — nothing is written.  Prints a per-user report and exits non-zero if
any check fails (so it can gate CI or a manual QA pass).

Usage (prod):
  AWS_PROFILE=gradgps DYNAMODB_ENDPOINT= S3_ENDPOINT= \
  AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= \
  python scripts/verify_transcripts.py [user_id ...]
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boto3.dynamodb.conditions import Key
from db import users_table, transcript_table, get_s3
from routers.transcript import S3_BUCKET
from transcript_parser import parse_and_detect, official_parse_looks_bad

VALID_TERM = re.compile(r"^(SP|SU|FA) \d{4}$")
# Normal catalog codes, plus XFR placeholder codes for generic transfer/test
# credit ('ENGL XFRGH') — real credits with no catalog course behind them.
VALID_CODE = re.compile(r"^[A-Z][A-Z-]{0,7} (\d{1,3}[A-Z]?|XFR[A-Z]{0,4})$")
VALID_GRADES = {"A", "A-", "B+", "B", "B-", "C+", "C", "D", "TR", ""}
# D is passing-with-credit at PSU; F/W rows are dropped by the parser.


def _key(c):
    return c.get("course_code", "").strip().upper()


def verify_user(user: dict) -> list[str]:
    """Return a list of problem strings for one user's transcript (empty = clean)."""
    uid = user["user_id"]
    problems: list[str] = []
    s3_key = user.get("transcript_s3_key")
    print("=" * 72)
    print(f"USER {uid}")
    print(f"  stored kind={user.get('transcript_kind', '-')}  s3_key={s3_key}")

    stored = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(uid)
    ).get("Items", [])
    print(f"  stored courses: {len(stored)}")

    if not s3_key:
        if stored:
            problems.append(f"{len(stored)} stored courses but no transcript_s3_key on user")
        else:
            print("  (no transcript uploaded — skipping)")
        return problems

    # ── 1. Re-parse the stored PDF with the current parser ───────────────────
    try:
        pdf_bytes = get_s3().get_object(Bucket=S3_BUCKET, Key=s3_key)["Body"].read()
    except Exception as e:
        problems.append(f"cannot fetch PDF from S3: {e}")
        return problems
    try:
        fresh, detection = parse_and_detect(pdf_bytes)
    except Exception as e:
        problems.append(f"parser crashed on stored PDF: {e!r}")
        return problems

    kind = "official" if detection.is_official else "unofficial"
    print(f"  re-parse: {len(fresh)} courses, detected={kind} "
          f"(score={getattr(detection, 'score', '?')})")

    # ── 2. Detection consistency ─────────────────────────────────────────────
    stored_kind = user.get("transcript_kind")
    if stored_kind and stored_kind != kind:
        problems.append(f"stored kind={stored_kind!r} but current detector says {kind!r}")
    if kind == "official" and official_parse_looks_bad(fresh):
        problems.append("official parse LOOKS BAD (too few courses or >30% Unknown terms) "
                        "— stored data is suspect")

    # ── 3. Fresh-parse integrity checks ──────────────────────────────────────
    seen: dict[str, dict] = {}
    unknown_terms = 0
    for c in fresh:
        code, term, grade = _key(c), c.get("term", ""), c.get("grade", "")
        cr, status = float(c.get("credits_earned", 0)), c.get("status", "")
        if not VALID_CODE.match(code):
            problems.append(f"malformed course code {code!r} (term {term})")
        if status != "transfer" and not VALID_TERM.match(term):
            unknown_terms += 1
        if grade not in VALID_GRADES and not re.match(r"^[A-DF][+-]?$", grade):
            problems.append(f"{code}: unexpected grade {grade!r}")
        if status == "done" and not (0 < cr <= 12):
            problems.append(f"{code}: done with implausible credits {cr}")
        if status == "in_progress" and cr != 0:
            problems.append(f"{code}: in_progress but credits_earned={cr} (expected 0)")
        if code in seen:
            problems.append(f"duplicate course {code} in fresh parse")
        seen[code] = c
    if unknown_terms:
        problems.append(f"{unknown_terms}/{len(fresh)} courses with unparseable term")

    # in-progress courses should all sit in the chronologically LATEST term
    def _tkey(t):
        m = VALID_TERM.match(t or "")
        return (int(t.split()[1]), {"SP": 0, "SU": 1, "FA": 2}[t.split()[0]]) if m else (0, 0)
    ip_terms = {c["term"] for c in fresh if c.get("status") == "in_progress"}
    done_terms = {c["term"] for c in fresh if c.get("status") == "done"}
    for t in ip_terms:
        if any(_tkey(d) > _tkey(t) for d in done_terms):
            problems.append(f"in_progress course in {t} but done courses exist in a LATER term")

    # ── 4. Stored-vs-fresh diff (parser drift / storage bugs) ────────────────
    stored_by = {_key(c): c for c in stored}
    fresh_by = {_key(c): c for c in fresh}
    only_stored = sorted(set(stored_by) - set(fresh_by))
    only_fresh = sorted(set(fresh_by) - set(stored_by))
    if only_stored:
        problems.append(f"in DB but NOT in re-parse: {', '.join(only_stored)}")
    if only_fresh:
        problems.append(f"in re-parse but NOT in DB: {', '.join(only_fresh)}")
    for code in sorted(set(stored_by) & set(fresh_by)):
        s, f = stored_by[code], fresh_by[code]
        for field in ("term", "grade", "status"):
            if str(s.get(field, "")) != str(f.get(field, "")):
                problems.append(f"{code}: {field} DB={s.get(field)!r} vs re-parse={f.get(field)!r}")
        if abs(float(s.get("credits_earned", 0)) - float(f.get("credits_earned", 0))) > 0.01:
            problems.append(f"{code}: credits DB={s.get('credits_earned')} "
                            f"vs re-parse={f.get('credits_earned')}")

    # ── 5. Report ────────────────────────────────────────────────────────────
    total_done = sum(float(c.get("credits_earned", 0)) for c in fresh
                     if c.get("status") in ("done", "transfer"))
    n_ip = sum(1 for c in fresh if c.get("status") == "in_progress")
    print(f"  earned credits (done+transfer): {total_done:g}   in-progress: {n_ip}")
    terms = sorted({c.get('term') for c in fresh if c.get('status') != 'transfer'}, key=_tkey)
    print(f"  terms: {terms}")
    return problems


def main(user_ids: list[str]):
    if user_ids:
        users = [users_table.get_item(Key={"user_id": u}).get("Item") for u in user_ids]
        users = [u for u in users if u]
    else:
        resp = users_table.scan()
        users = resp["Items"]
        while "LastEvaluatedKey" in resp:
            resp = users_table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
            users.extend(resp["Items"])

    failed = 0
    for user in users:
        problems = verify_user(user)
        if problems:
            failed += 1
            print(f"  ** {len(problems)} PROBLEM(S):")
            for p in problems:
                print(f"     - {p}")
        else:
            print("  OK — parse is stable and passes all integrity checks")

    print("=" * 72)
    print(f"{len(users)} user(s) checked, {failed} with problems")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
