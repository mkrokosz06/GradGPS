"""
Seed the App Store review DEMO account.

WHY: App Store guideline 2.1 requires a reviewer to be able to evaluate the
whole app. A reviewer has no Penn State account and no PSU transcript, so
signing in normally would land them in an empty shell. This script seeds one
synthetic student -- a fabricated person, NOT a real record -- behind the
env-gated review sign-in in `routers/email_auth.py` (`_review_account`:
REVIEW_EMAIL + REVIEW_CODE), so the reviewer sees a fully populated audit,
timeline, home dashboard and course screens on first launch.

The user_id is derived from the demo email exactly the way the email-OTP path
derives it (`email:<normalized-address>`), so the account this seeds is the
same one that sign-in resolves to.

Local:
    python scripts/seed_demo_account.py --audit

Production (see CLAUDE.md; run `aws sso login --profile gradgps` first):
    AWS_PROFILE=gradgps DYNAMODB_ENDPOINT= S3_ENDPOINT= \
    AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= \
    DEMO_EMAIL=<the address in REVIEW_EMAIL> python scripts/seed_demo_account.py

Options:
    --email <addr>   override the demo address (defaults to $DEMO_EMAIL, then
                     $REVIEW_EMAIL, then DEFAULT_DEMO_EMAIL below)
    --audit          run a live audit afterwards and print a summary
    --dry-run        print what would be written, write nothing

Idempotent: re-running replaces the user row and the transcript rows wholesale
(stale rows from a previous shape are deleted first), so it is safe to re-run.
It touches ONLY this one user's rows -- it never patches the catalog (use
scripts/apply_catalog_patches.py for that) and never writes another user.

NOTE ON THE DATA: every name and grade below is invented. The course history is
assembled from the *real* PSU catalog (so the audit and the SAP timeline
actually resolve) but belongs to no real student.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from boto3.dynamodb.conditions import Key

from db import users_table, transcript_table, requirements_table

# -- Identity ---------------------------------------------------------------
# A neutral address on a domain we control. The real value lives in the
# REVIEW_EMAIL env var on the server; this is only the seeding default, and is
# not a secret (the *code* is, and is never stored in this repo).
DEFAULT_DEMO_EMAIL = "appreview@gradgps.com"

DEMO_NAME = "Alex Demo"          # fabricated -- not a real person

# Mirrors deps._USER_ID_RE. Re-asserted here so a bad --email fails loudly at
# seed time rather than producing a row nothing can ever authenticate into.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._@-]{0,127}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# -- Program ----------------------------------------------------------------
# Chosen because it (a) has a published Suggested Academic Plan template, so
# the reviewer sees the richer SAP timeline rather than the fallback packer,
# (b) has no subplans/options to disambiguate, and (c) has no world-language
# pool or open-ended elective blocks that would render as vague placeholders.
MAJOR = "Computer Engineering, B.S. (Engineering)"
SUBPLAN = None

# -- The synthetic transcript ------------------------------------------------
# Two and a half years of a Computer Engineering student, drawn from the real
# catalog and ordered along the published plan, plus a summer term and one
# in-progress term. Titles/credits are looked up from bulletin_courses.json at
# run time; the number here is the fallback if the bulletin has no entry.
#   (code, grade, credits, term, status)
_DONE, _IP = "done", "in_progress"

TRANSCRIPT = [
    # Year 1 -- Fall
    ("MATH 140",  "A-", 4.0, "FA 2024", _DONE),
    ("PHYS 211",  "B+", 4.0, "FA 2024", _DONE),
    ("CHEM 110",  "B",  3.0, "FA 2024", _DONE),
    ("ENGL 15",   "A",  3.0, "FA 2024", _DONE),
    ("PSYCH 100", "A-", 3.0, "FA 2024", _DONE),   # GS
    # Year 1 -- Spring
    ("CMPSC 131", "A",  3.0, "SP 2025", _DONE),
    ("MATH 141",  "B",  4.0, "SP 2025", _DONE),
    ("PHYS 212",  "B+", 4.0, "SP 2025", _DONE),
    ("CAS 100A",  "A-", 3.0, "SP 2025", _DONE),
    ("MUSIC 9",   "A",  3.0, "SP 2025", _DONE),   # GA + IL
    # Summer
    ("HIST 20",   "A",  3.0, "SU 2025", _DONE),   # GH + US
    ("KINES 11",  "A",  1.5, "SU 2025", _DONE),   # GHW
    # Year 2 -- Fall
    ("CMPEN 270", "B+", 4.0, "FA 2025", _DONE),
    ("CMPSC 132", "A-", 3.0, "FA 2025", _DONE),
    ("MATH 250",  "B",  3.0, "FA 2025", _DONE),
    ("MATH 220",  "A",  2.0, "FA 2025", _DONE),
    ("PHYS 214",  "B+", 2.0, "FA 2025", _DONE),
    # Year 2 -- Spring
    ("CMPEN 331", "B+", 4.0, "SP 2026", _DONE),
    ("CMPSC 221", "A-", 3.0, "SP 2026", _DONE),
    ("EE 210",    "B",  4.0, "SP 2026", _DONE),
    ("MATH 231",  "B+", 2.0, "SP 2026", _DONE),
    ("ECON 102",  "A",  3.0, "SP 2026", _DONE),   # GS
    # Year 3 -- Fall, in progress (no grades yet)
    ("CMPEN 431", "", 3.0, "FA 2026", _IP),
    ("CMPSC 311", "", 3.0, "FA 2026", _IP),
    ("EE 310",    "", 4.0, "FA 2026", _IP),
    ("STAT 418",  "", 3.0, "FA 2026", _IP),
    ("CMPSC 360", "", 3.0, "FA 2026", _IP),
]


# -- Helpers -----------------------------------------------------------------

def demo_email(cli_value):
    email = (cli_value or os.getenv("DEMO_EMAIL") or os.getenv("REVIEW_EMAIL")
             or DEFAULT_DEMO_EMAIL).strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        sys.exit("Not a valid email address: %r" % email)
    return email


def demo_user_id(email):
    """Same derivation as routers/email_auth.email_verify."""
    uid = "email:%s" % email
    if not _USER_ID_RE.match(uid):
        # e.g. plus-addressing: "+" is not in deps._USER_ID_RE, so such an
        # address would seed a row that sign-in could never reach.
        sys.exit(
            "user_id %r would be rejected by deps._USER_ID_RE -- pick a demo "
            "address using only [A-Za-z0-9:._@-]." % uid
        )
    return uid


def _bulletin():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "bulletin_courses.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_courses():
    """Expand TRANSCRIPT into stored-row shape, taking title/credits from the
    bulletin where it knows the course."""
    bul = _bulletin()
    out = []
    for code, grade, credits, term, status in TRANSCRIPT:
        meta = bul.get(code) or {}
        cr = float(meta.get("credits") or credits)
        out.append({
            "course_code":    code,
            "course_title":   (meta.get("title") or code)[:120],
            "grade":          grade,
            "credits":        cr,
            "credits_earned": cr if status == _DONE else 0.0,
            "term":           term,
            "status":         status,
            "is_writing":     bool(re.search(r"[WMXY]$", code)),
        })
    return out


def check_catalog():
    """Warn loudly if the catalog doesn't have the demo major -- seeding against
    an unloaded DB would produce an empty audit, which is the exact failure this
    account exists to prevent."""
    resp = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(MAJOR),
        ProjectionExpression="course_code",
    )
    n = len(resp.get("Items", []))
    if n == 0:
        print("  !! WARNING: no requirement rows for %r. Run load_catalog.py "
              "(+ the patch scripts) first -- the demo account will otherwise "
              "show an empty audit." % MAJOR)
    else:
        print("  catalog: %d requirement rows for %s" % (n, MAJOR))


def seed_user(user_id, email, dry):
    item = {
        "user_id":    user_id,
        "name":       DEMO_NAME,
        "email":      email,
        "major":      MAJOR,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_demo":    True,      # so the row is identifiable in the admin list
    }
    if SUBPLAN:
        item["subplan"] = SUBPLAN
    print("\nUser row: %s" % user_id)
    print("  name  : %s   (synthetic)" % DEMO_NAME)
    print("  email : %s" % email)
    print("  major : %s" % MAJOR)
    if dry:
        return
    users_table.put_item(Item=item)


def seed_courses(user_id, courses, dry):
    # Idempotency: clear whatever is there first, so a re-run with a changed
    # TRANSCRIPT can never leave an orphan row behind.
    existing = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(user_id),
        ProjectionExpression="course_code",
    ).get("Items", [])
    print("\nTranscript: replacing %d existing row(s) with %d"
          % (len(existing), len(courses)))
    if not dry:
        with transcript_table.batch_writer() as batch:
            for r in existing:
                batch.delete_item(Key={"user_id": user_id,
                                       "course_code": r["course_code"]})
        with transcript_table.batch_writer() as batch:
            for c in courses:
                batch.put_item(Item={
                    "user_id":        user_id,
                    "course_code":    c["course_code"],
                    "course_title":   c["course_title"],
                    "grade":          c["grade"],
                    "credits":        Decimal(str(c["credits"])),
                    "credits_earned": Decimal(str(c["credits_earned"])),
                    "term":           c["term"],
                    "status":         c["status"],
                    "is_writing":     c["is_writing"],
                })

    by_term = {}
    for c in courses:
        by_term.setdefault(c["term"], []).append(c)
    for term, rows in by_term.items():
        cr = sum(r["credits"] for r in rows)
        print("  %-8s %2d courses  %5.1f cr  (%s)"
              % (term, len(rows), cr, rows[0]["status"]))
    print("  earned credits: %g"
          % sum(c["credits_earned"] for c in courses))


def run_audit_summary(user_id):
    from audit_engine import run_audit
    courses = transcript_table.query(
        KeyConditionExpression=Key("user_id").eq(user_id)
    ).get("Items", [])
    rows = requirements_table.query(
        KeyConditionExpression=Key("program_name").eq(MAJOR)
    ).get("Items", [])
    result = run_audit(rows, courses)
    print("\nAudit (%s):" % MAJOR)
    for key in ("total", "done", "in_progress", "missing", "credits_earned"):
        if key in result:
            print("  %-14s %s" % (key, result[key]))
    if not result.get("done"):
        print("  !! nothing satisfied -- the catalog is probably unpatched, or "
              "the major name has drifted.")


def main():
    ap = argparse.ArgumentParser(description="Seed the App Review demo account.")
    ap.add_argument("--email", help="demo address (default: $DEMO_EMAIL / $REVIEW_EMAIL)")
    ap.add_argument("--audit", action="store_true", help="print an audit summary afterwards")
    ap.add_argument("--dry-run", action="store_true", help="write nothing")
    args = ap.parse_args()

    email = demo_email(args.email)
    user_id = demo_user_id(email)

    print("Target DynamoDB: %s" % (os.getenv("DYNAMODB_ENDPOINT") or "REAL AWS"))
    if args.dry_run:
        print("DRY RUN -- nothing will be written.")

    check_catalog()
    seed_user(user_id, email, args.dry_run)
    seed_courses(user_id, build_courses(), args.dry_run)

    if args.audit and not args.dry_run:
        run_audit_summary(user_id)

    print("\nDone. The reviewer signs in with this address and the 6-digit "
          "REVIEW_CODE set on the server\n(see routers/email_auth._review_account).")


if __name__ == "__main__":
    main()
