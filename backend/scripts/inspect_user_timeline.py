"""Diagnostic: dump a user's major, transcript courses (by term), the audit's
missing items, and the computed future-semester timeline.  Read-only.

Usage:
  AWS_PROFILE=gradgps DYNAMODB_ENDPOINT= S3_ENDPOINT= \
  AWS_ACCESS_KEY_ID= AWS_SECRET_ACCESS_KEY= \
  python scripts/inspect_user_timeline.py <user_id>
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from boto3.dynamodb.conditions import Key
from db import requirements_table, users_table, transcript_table
from audit_engine import run_audit, run_gen_ed_audit
from routers.audit import _filter_rows
from plan_templates import load_template
import routers.timeline as tl


def main(user_id):
    user = users_table.get_item(Key={"user_id": user_id}).get("Item")
    print("=" * 70)
    print("USER:", user_id)
    if not user:
        print("  !! no user record"); return
    major = user.get("major"); subplan = user.get("subplan")
    print("  major:  ", major)
    print("  subplan:", subplan)
    print("  transcript_kind:", user.get("transcript_kind"))

    tx = transcript_table.query(KeyConditionExpression=Key("user_id").eq(user_id)).get("Items", [])
    print(f"\nTRANSCRIPT COURSES ({len(tx)}):")
    from collections import defaultdict
    byterm = defaultdict(list)
    for c in tx:
        byterm[c.get("term") or "??"].append(c)
    for term in sorted(byterm, key=tl._term_key):
        courses = byterm[term]
        print(f"  [{term}]  ({len(courses)} courses)")
        for c in sorted(courses, key=lambda x: x.get("course_code", "")):
            print(f"      {c.get('course_code',''):12} {c.get('status',''):12} "
                  f"cr={c.get('credits_earned','?')!s:5} grade={c.get('grade','')!s:4} "
                  f"{(c.get('course_title','') or '')[:32]}")

    sorted_terms = sorted(byterm.keys(), key=tl._term_key)
    print("\n  sorted_terms:", sorted_terms)
    print("  base_term (last):", sorted_terms[-1] if sorted_terms else None)

    # requirements
    req = requirements_table.query(KeyConditionExpression=Key("program_name").eq(major)).get("Items", [])
    taken_codes = {c.get("course_code", "").strip().upper() for c in tx}
    req = _filter_rows(req, subplan, taken_codes)
    template = load_template(major, subplan)
    print("\n  requirement rows (filtered):", len(req))
    print("  has SAP template:", bool(template))

    audit = run_audit(req, tx)
    missing = tl._collect_missing(audit)
    print(f"\nAUDIT MISSING ITEMS ({len(missing)}):")
    for m in missing:
        tag = "POOL" if m.get("is_pool") else "    "
        print(f"  {tag} {m.get('course_code',''):28} cr={m.get('credits','?')!s:5} {(m.get('course_title','') or '')[:36]}")

    # SAP template match detail
    if template:
        from sap_schedule import (build_taken_set, build_gen_ed_satisfied,
                                   build_used_codes, match_template)
        gen_ed_result = run_gen_ed_audit(
            requirements_table.query(KeyConditionExpression=Key("program_name").eq("__GEN_ED__")).get("Items", []),
            tx,
        )
        records = match_template(
            template,
            build_taken_set(tx),
            build_gen_ed_satisfied(gen_ed_result),
            transcript_courses=tx,
            used_codes=build_used_codes(audit, gen_ed_result),
        )
        print("\nGEN-ED AUDIT GROUPS:")
        for g in gen_ed_result.get("groups", []):
            print(f"  {'OK' if g.get('satisfied') else ' .'} {g.get('name','')[:40]:40} "
                  f"type={g.get('group_type','')} earned={g.get('credits_earned')} done={g.get('done')} thr={g.get('threshold')}")
        from sap_schedule import _leftover_courses, build_used_codes as _buc
        uc = build_used_codes(audit, gen_ed_result)
        consumed_now = {r["matched_code"] for r in records if r["satisfied"] and r["matched_code"]}
        lo = _leftover_courses(tx, consumed_now, uc)
        print(f"\nLEFTOVER (surplus) courses ({len(lo)}):",
              ", ".join(sorted(c.get("course_code","") for c in lo)))
        print("used_codes (audit-consumed):", ", ".join(sorted(uc)))

        nsat = sum(1 for r in records if r["satisfied"])
        print(f"\nSAP TEMPLATE MATCH ({len(records)} slots, {nsat} satisfied, {len(records)-nsat} remaining):")
        for r in records:
            slot = r["slot"]
            code = slot.get("code") or "/".join(slot.get("codes", [])) or slot.get("category") or slot.get("label") or slot.get("type")
            mark = "OK " if r["satisfied"] else " . "
            print(f"  sem{r['sem_index']:>2} {r.get('season') or '':2} {mark} {slot.get('type'):10} {str(code)[:34]:34} "
                  f"{'<= '+str(r['matched_code']) if r['satisfied'] else ''}")

    # run the real timeline endpoint logic
    from routers.timeline import get_timeline
    result = get_timeline.__wrapped__(user_id) if hasattr(get_timeline, "__wrapped__") else None
    try:
        result = get_timeline(user_id=user_id)
    except Exception as e:
        print("  timeline error:", e); result = None
    if result:
        print("\nTIMELINE SEMESTERS:")
        for s in result["semesters"]:
            n = len(s["courses"])
            print(f"  {s['term']:12} {s['status']:10} {s['credits']!s:6}cr  ({n} courses)")
        fut = [s for s in result["semesters"] if s["status"] == "upcoming"]
        print(f"\n  -> {len(fut)} FUTURE semesters projected")
        if fut:
            print(f"  -> graduation term: {fut[-1]['term']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "google:105287226824376813082")
