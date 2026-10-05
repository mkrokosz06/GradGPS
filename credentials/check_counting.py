"""Check that every credential COUNTS courses correctly, not just that it parses.

    python credentials/check_counting.py

For each credential: build a transcript that completes it with each course used
once, run the app's own credential audit (credentials_audit: exclusive counting
plus the credit-range total), then check that (1) it reads complete, (2) removing
any one course makes it incomplete -- otherwise a course is counted twice or two
pools merged -- and (3) it reaches PSU's stated total.

Oct 2026: 207 of 209 complete. The other two (Biomedical Engineering,
Sustainability Leadership) are limits of this script, not the audit: it takes a
variable-credit course at its minimum and doesn't spread extra credits across
adviser ranges. "course not needed" lines are mostly the script over-picking (a
4-credit course where 3 would do), and "completes below" lines are variable-credit
courses taken at their minimum; read them rather than count them.
"""
import json, os, re, sys
from collections import defaultdict, Counter

BACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, BACK)
os.chdir(BACK)

import credential_catalog as cc
from audit_engine import _in_dept_pool, _split_course_code
from transcript_parser import _normalise_code

BULLETIN = json.load(open("scripts/bulletin_courses.json", encoding="utf-8"))


def bcredits(code, row_credits=None):
    info = BULLETIN.get(code) or BULLETIN.get(re.sub(r"(\d)[WHMN]$", r"\1", code)) or {}
    c = info.get("credits") or row_credits or 3
    return float(c)


def tx_row(code, credits):
    stored = _normalise_code(code)
    return {"course_code": stored, "status": "done", "grade": "", "credits_earned": credits,
            "is_writing": bool(re.search(r"\d[WMXY]$", code)), "raw_code": code}


def minimal_transcript(entry, rows):
    """A transcript that completes the credential with each course used once:
    every group gets its own courses, then pools with headroom (a range's top)
    take more until PSU's total is reached."""
    used = set()
    tx = []
    attested = {}
    notes = []
    headroom = []   # (group, candidates, top, picked_credits) for the total top-up

    def take(code, credits=None):
        base = _normalise_code(code)
        if base in used:
            return 0.0
        used.add(base)
        cr = credits if credits is not None else bcredits(code)
        tx.append(tx_row(code, cr))
        return cr

    for gi, g in enumerate(entry["groups"]):
        gt = g["group_type"]
        courses = g.get("courses", [])
        thr = float(g.get("threshold") or 0)
        top = max(thr, float(g.get("threshold_max") or 0))
        if gt == "required":
            for c in courses:
                take(c["course_code"])
        elif gt == "choose_one":
            pairs = defaultdict(list)
            for c in courses:
                pairs[c.get("pair_group_id") or ("solo", c["course_code"])].append(c)
            for opts in pairs.values():
                for o in opts:
                    if take(o["course_code"]):
                        break
        elif gt in ("choose_credits", "choose_courses"):
            have = 0.0
            for c in courses:
                if have >= thr:
                    break
                cr = take(c["course_code"])
                have += (1 if cr else 0) if gt == "choose_courses" else cr
            if have < thr:
                notes.append(f"pool '{g['name']}' can't reach {thr} from its own unused courses ({have})")
            if gt == "choose_credits" and top > have:
                headroom.append([g, [c["course_code"] for c in courses], top, have])
        elif gt == "dept_credits":
            row = next(r for r in rows if r["group_type"] == "dept_credits" and r["requirement_group"] == g["name"])
            spec = {k: row[k] for k in ("dept", "depts", "min_level", "max_level", "sub_level", "sub_credits", "exclude", "include") if row.get(k) not in (None, [], "")}
            sub_level, sub_credits = spec.get("sub_level"), float(spec.get("sub_credits") or 0)
            cands = [c for c in list(spec.get("include", [])) + list(BULLETIN) if _in_dept_pool(c, spec)
                     and not re.search(r"\d[WHMN]$", c) and 1 <= bcredits(c) <= 4]
            have = lvl = 0.0
            if sub_level:
                for c in cands:
                    if lvl >= sub_credits or have >= thr:
                        break
                    p = _split_course_code(c)
                    if p and p[1] >= sub_level:
                        cr = take(c)
                        have += cr; lvl += cr
            for c in cands:
                if have >= thr:
                    break
                have += take(c)
            if have < thr:
                notes.append(f"dept pool '{g['name']}' only {have}/{thr} from bulletin")
            if top > have:
                headroom.append([g, cands, top, have])
        elif gt == "unstructured_credits":
            have, i = 0.0, 0
            if top > thr:
                headroom.append([g, None, top, 0.0, gi])
            if not thr and (not top or "proficien" in ((g.get("pool") or {}).get("text") or "").lower()):
                thr = 0.1   # a no-credit / proficiency item: name one course
            while have < thr:
                code = f"ZZAD {100 + gi * 10 + i}"
                tx.append(tx_row(code, 3.0)); used.add(code)
                attested.setdefault(g["name"], []).append(code)
                have += 3.0; i += 1

    # Top up toward PSU's total from pools that still have room.
    required = cc.required_total(entry) if any((g.get("threshold_max") or 0) > (g.get("threshold") or 0) for g in entry["groups"]) else 0
    total = lambda: sum(t["credits_earned"] for t in tx)
    for h in headroom:
        g, cands, top, have = h[:4]
        if cands is None:          # adviser block: the student names more courses
            i = 50
            while total() < required and have < top:
                code = f"ZZAD {100 + h[4] * 10 + i}"
                tx.append(tx_row(code, 3.0)); used.add(code)
                attested.setdefault(g["name"], []).append(code)
                have += 3.0; i += 1
            continue
        for c in cands:
            if total() >= required or have >= top:
                break
            have += take(c)
    if total() < required:
        notes.append(f"no room to reach {required} (have {total()})")
    return tx, attested, notes


import credentials_audit, credential_choices
_SEP = credential_choices._SEP
CURRENT = {}


def complete(rows, tx, attested):
    name = CURRENT["name"]
    att = {f"{name}{_SEP}{g}": v for g, v in attested.items()}
    res = credentials_audit.audit_declared_credentials({"credentials": [{"program": name}]}, tx, None, att)[0]
    return all(g["satisfied"] for g in res["groups"]), res


def main():
    cat = cc._catalog()
    report = defaultdict(list)
    for name, entry in sorted(cat.items()):
        rows = cc.to_requirement_rows(entry)
        CURRENT["name"] = name

        # Data shape checks
        seen = Counter()
        for g in entry["groups"]:
            for c in {_normalise_code(c["course_code"]) for c in g.get("courses", [])}:
                seen[c] += 1
        dups = [c for c, n in seen.items() if n > 1]
        if dups:
            # Informational: the page lists a course twice; exclusive counting
            # makes it fill one requirement only.
            report["course listed in two groups (info)"].append(f"{name}: {', '.join(sorted(dups)[:6])}")

        tx, attested, notes = minimal_transcript(entry, rows)
        for n in notes:
            report["can't build"].append(f"{name}: {n}")
        ok, res = complete(rows, tx, attested)
        if not ok:
            bad = [g["name"] for g in res["groups"] if not g["satisfied"]]
            report["NOT complete with a completing transcript"].append(f"{name}: unsatisfied {bad}")
            continue
        tx_total = sum(t["credits_earned"] for t in tx)
        lo = entry["credits"]["min"]; stated = entry.get("stated_credits")
        if tx_total + 0.01 < lo:
            report["completes below catalog minimum"].append(f"{name}: {tx_total} < {lo}")
        if stated and entry.get("agrees") and tx_total + 0.01 < stated:
            report["completes below PSU stated total"].append(f"{name}: {tx_total} < stated {stated}")
        reported = res.get("credits_counted")
        if reported is not None and abs(float(reported) - tx_total) > 0.01:
            report["audit credit total != transcript"].append(f"{name}: audit {reported} vs transcript {tx_total}")
        # Necessity: every course should matter.
        spare = []
        for i, t in enumerate(tx):
            rest = tx[:i] + tx[i + 1:]
            att = {k: [c for c in v if c != t["course_code"]] for k, v in attested.items()}
            if complete(rows, rest, att)[0]:
                spare.append(t["raw_code"])
        if spare:
            report["course not needed (double count / merged pool?)"].append(f"{name}: {', '.join(spare[:6])}")
        report["_checked"].append(name)

    for k, v in report.items():
        if k == "_checked":
            continue
        print(f"\n## {k} ({len(v)})")
        for line in v:
            print("  ", line)
    print(f"\nchecked {len(report['_checked'])} of {len(cat)} credentials end to end")


if __name__ == "__main__":
    main()
