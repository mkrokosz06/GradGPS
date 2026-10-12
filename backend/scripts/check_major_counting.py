"""Complete-then-drop sweep over every University Park major (the majors' twin of
credentials/check_counting.py).

    python scripts/check_major_counting.py [--major SUBSTR] [--pairs]

Needs the local catalog (docker-compose + load_catalog.py). Read-only.

For every UP degree program x option x Application Focus area:
  1. build a transcript that should finish the major, using the app's own row
     filter (_filter_rows) the way GET /audit does;
  2. check run_audit() reads every group satisfied;
  3. drop each course in turn -- a course taken for a required / choose-one row
     whose removal leaves the major complete means that row isn't enforced; a
     pool course whose removal leaves its pool short on its own list, yet the
     audit complete, means the pool isn't enforced (merged with another);
  4. with no option chosen, check the app's option auto-pick (driven by the
     transcript) lands on the option the transcript was built for.

--pairs also runs a sample of major + minor/certificate combinations through
credentials_audit, checking that the two audits complete together and that
declaring the credential's courses doesn't change the major's result.
"""
import argparse, json, os, re, sys
from collections import defaultdict

BACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACK)
os.chdir(BACK)

from boto3.dynamodb.conditions import Key
from db import requirements_table
from audit_engine import run_audit, _type_buckets, _build_taken, _find_entry, _pool_spec, _in_dept_pool
from transcript_parser import _normalise_code
from routers.audit import _filter_rows, get_subplans, _CAMPUS_RE
from routers.programs import _load_all_programs, focus_areas

BULLETIN = json.load(open("scripts/bulletin_courses.json", encoding="utf-8"))
_KNOWN_TYPES = ("required", "choose_one", "choose_credits", "choose_courses", "dept_credits",
                "unstructured_credits", "writing_intensive")


def binfo(code):
    return BULLETIN.get(code) or BULLETIN.get(re.sub(r"(\d)[WHMN]$", r"\1", code)) or {}


def tx_row(code, credits, status="done"):
    return {"course_code": _normalise_code(code), "status": status, "grade": "A",
            "credits_earned": credits, "is_writing": bool(re.search(r"\d[WMXY]$", code)),
            "raw_code": code}


def program_rows(name):
    rows, kw = [], {"KeyConditionExpression": Key("program_name").eq(name)}
    while True:
        r = requirements_table.query(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            return rows
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def norm(code):
    return _normalise_code(code.strip().upper())


def build_transcript(rows):
    """A transcript that completes `rows` (courses may serve several groups, as
    majors allow). Returns (tx, why, pools, notes): why[code] is what the course was
    taken for; pools is [(group, type, threshold, member codes)]."""
    tx, why, have = [], {}, {}
    row_credits = {r["course_code"]: r.get("credits") for r in rows}

    def take(code, reason):
        b = norm(code)
        if b in have:
            return 0.0
        cr = float(binfo(code.strip().upper()).get("credits") or row_credits.get(code) or 3)
        have[b] = cr
        tx.append(tx_row(code.strip().upper(), cr))
        why[tx[-1]["course_code"]] = reason
        return cr

    by_group = defaultdict(list)
    for r in rows:
        by_group[r.get("requirement_group", "General Requirements")].append(r)
    pending = []
    # Named requirements first so pools can count what's already there.
    for g, grows in by_group.items():
        buckets = _type_buckets(grows)
        for (gtype, thr, seq), brows in buckets.items():
            if len(buckets) == 1:
                thr = int(grows[0]["group_threshold"]) if grows[0].get("group_threshold") else None
            if gtype not in _KNOWN_TYPES or gtype == "required":
                for r in brows:      # the engine evaluates an unknown type as required
                    take(r["course_code"], "required" if gtype == "required" else f"type:{gtype}")
            elif gtype == "choose_one":
                pairs = defaultdict(list)
                for i, r in enumerate(brows):
                    pairs[str(r.get("pair_group_id") or f"solo{i}")].append(r)
                for prs in pairs.values():
                    branches = defaultdict(list)
                    for i, r in enumerate(prs):
                        branches[str(r.get("pair_branch_id") or f"b{i}")].append(r)
                    if any(all(norm(m["course_code"]) in have for m in b) for b in branches.values()):
                        continue
                    for m in next(iter(branches.values())):
                        take(m["course_code"], "choose_one")
            else:
                pending.append((g, gtype, thr, brows))
    notes, pools = [], []
    # Subject/level rules last, narrowest first, so a 3-credit range pool picks
    # its course before the 12-credit pool over every range counts it too (a major
    # audit shares courses between pools).
    pending.sort(key=lambda p: (p[1] == "dept_credits", p[2] or 0 if p[1] == "dept_credits" else 0))
    for g, gtype, thr, brows in pending:
        if gtype == "dept_credits":
            spec = _pool_spec(brows)
            members = {b for b in have if _in_dept_pool(b, spec)}
            got = sum(have[b] for b in members)
            cands = [c for c in list(spec.get("include", [])) + list(BULLETIN)
                     if _in_dept_pool(c, spec) and not re.search(r"\d[WHMN]$", c)
                     and 1 <= float(BULLETIN.get(c, {}).get("credits") or 3) <= 4]
            for c in cands:
                if got >= (thr or 0):
                    break
                cr = take(c, "pool")
                if cr:
                    members.add(norm(c))
                    got += cr
            pools.append((g, gtype, thr, members))
            if got < (thr or 0):
                notes.append(f"dept pool '{g}' ({thr}) only reaches {got} from the bulletin")
            continue
        if gtype not in ("choose_credits", "choose_courses"):
            notes.append(f"unhandled group type {gtype} in '{g}'")
            continue
        if thr is None:
            continue
        members = {norm(r["course_code"]) for r in brows}
        pools.append((g, gtype, thr, members))
        val = lambda b: 1 if gtype == "choose_courses" else have[b]
        got = sum(val(b) for b in members if b in have)
        for r in brows:
            if got >= thr:
                break
            if norm(r["course_code"]) in have:
                continue
            take(r["course_code"], "pool")
            got += val(norm(r["course_code"]))
        if got < thr and gtype == "choose_credits":
            # variable-credit courses (co-op, independent study) at their max
            for t in tx:
                if got >= thr:
                    break
                mx = binfo(t["raw_code"]).get("credits_max")
                if t["course_code"] in members and mx and t["credits_earned"] < mx:
                    got += mx - t["credits_earned"]
                    have[t["course_code"]] = t["credits_earned"] = float(mx)
        if got < thr:
            notes.append(f"pool '{g}' ({gtype} {thr}) only reaches {got} from its own list")
    return tx, why, pools, notes


_SECTION = re.compile(r"^([A-Z][A-Z\-]* \d+)$")


def in_bulletin(code):
    """Whether a requirement code is a real bulletin course: as written, without its
    W/H/M/N attribute suffix, or as the bare form of suffixed / section-letter
    courses (PHIL 103 -> PHIL 103W, CAS 100 -> CAS 100A/B/C)."""
    code = re.sub(r"\s+", " ", code.strip().upper())
    if code in BULLETIN or re.sub(r"(\d)[WHMN]$", r"\1", code) in BULLETIN:
        return True
    if _SECTION.match(code):
        return any(f"{code}{x}" in BULLETIN for x in "ABCDEFGHMNSTUWXY")
    return False


def invented_codes(name, all_rows, report):
    """Requirement codes the app would audit that aren't on the bulletin: prose the
    scraper cut into a course ("ANTH 400" from "ANTH 400-419"), or a retired course.
    Plan-grid duplicate groups (dropped by _filter_rows) are skipped."""
    for r in all_rows:
        g, code = r.get("requirement_group", ""), (r.get("course_code") or "").strip()
        if _CAMPUS_RE.search(g) or "suggested academic plan" in g.lower() or code.startswith("__"):
            continue
        if not re.match(r"^[A-Z]+ \d", code.upper()) or in_bulletin(code):
            continue    # bulletin_courses.json has no hyphenated subjects (A-I, B M B)
        title = str(r.get("course_title") or "")
        prose = bool(re.search(r"level|select|credits|-\d|\(other than|any ", title, re.I))
        key = ("code not in bulletin, title is prose (likely invented)" if prose
               else "code not in bulletin (retired/renamed course, or invented)")
        report[key].append(f"{name} | {g[:50]} | {code} | {title[:60]} | {r.get('group_type')}")


def pool_short(rest, gtype, thr, members):
    """Whether the remaining transcript reaches a pool's threshold on its own list,
    matched the way the engine matches (cross-listings, suffix variants)."""
    taken = _build_taken(rest)
    entries = {id(e): e for e in (_find_entry(c, taken) for c in members) if e}
    got = sum(1 if gtype == "choose_courses" else e["credits_earned"] for e in entries.values())
    return got < thr


def unsatisfied(res):
    out = []
    for g in res["groups"]:
        if g["satisfied"]:
            continue
        if g.get("sub_groups"):
            for s in g["sub_groups"]:
                if not s["satisfied"]:
                    out.append(f"{g['name']} [{s['sub_type']} {s['threshold']}]")
        else:
            out.append(f"{g['name']} [{g['group_type']} {g['threshold']}]")
    return out


def audit(all_rows, subplan, focus, tx):
    taken_codes = {c["course_code"].strip().upper() for c in tx}
    rows = _filter_rows(all_rows, subplan, taken_codes, focus)
    return rows, run_audit(rows, tx)


def check_combo(name, all_rows, subplan, focus, report):
    label = f"{name}" + (f" / {subplan}" if subplan else "") + (f" / focus={focus}" if focus else "")
    seed = _filter_rows(all_rows, subplan, set(), focus)
    if not seed:
        report["no requirement rows after the app's filter"].append(label)
        return
    tx, why, pools, notes = build_transcript(seed)
    for n in notes:
        report["pool can't be completed from its own list (data)"].append(f"{label}: {n}")
    gen = sorted({w for w in why.values() if w.startswith("type:")})
    if gen:
        report["unknown group type, evaluated as required"].append(f"{label}: {gen}")
    rows, res = audit(all_rows, subplan, focus, tx)
    if not subplan:
        g0 = {r["requirement_group"] for r in seed}
        g1 = {r["requirement_group"] for r in rows}
        if g0 != g1:
            report["option auto-pick switched under the transcript"].append(
                f"{label}: built for {sorted(g0 - g1)[:2]} got {sorted(g1 - g0)[:2]}")
    bad = unsatisfied(res)
    if bad:
        report["NOT complete with a completing transcript"].append(f"{label}: {bad[:4]}")
        return
    named, pooled = [], []
    for i, t in enumerate(tx):
        rest = tx[:i] + tx[i + 1:]
        if unsatisfied(audit(all_rows, subplan, focus, rest)[1]):
            continue
        if why[t["course_code"]] != "pool":
            named.append(t["raw_code"])
            continue
        short = [g for g, gt, th, mem in pools if t["course_code"] in mem and pool_short(rest, gt, th, mem)]
        if short:
            pooled.append(f"{t['raw_code']} ({short[0][:50]})")
    if named:
        report["named course not enforced (drop it, still complete)"].append(f"{label}: {', '.join(named[:8])}")
    if pooled:
        report["pool short but audit complete (pool not enforced)"].append(f"{label}: {', '.join(pooled[:4])}")
    report["_checked"].append(label)


# Major + credential pairs a real student might declare: business, science,
# engineering, liberal arts, IST, health, and two certificates.
PAIRS = [
    ("Enterprise Technology Integration, B.S.", "Cybersecurity Computational Foundations, Minor"),
    ("Finance, B.S.", "Economics, Minor"),
    ("Mechanical Engineering, B.S.", "Electrochemical Engineering, Minor"),
    ("Psychology, B.S.", "Sociology, Minor"),
    ("Computer Science, B.S.", "Computer Engineering, Minor (Engineering)"),
    ("Biology, B.S.", "Nutritional Sciences, Minor"),
    ("Accounting, B.S.", "Spanish, Minor"),
    ("Political Science, B.A.", "English, Minor (Liberal Arts)"),
    ("Kinesiology, B.S.", "Nutrition Studies, Minor"),
    ("Marketing, B.S.", "Psychology, Minor"),
    ("Cybersecurity Analytics and Operations, B.S.", "Global Spanish for Business, Certificate"),
    ("Supply Chain and Information Systems, B.S.", "Business and the Liberal Arts, Minor"),
]


def check_pairs(majors, report):
    import credential_catalog as cc
    sys.path.insert(0, os.path.join(BACK, "..", "credentials"))
    import check_counting as ccnt
    import credentials_audit
    creds = cc._catalog()
    for major_hint, cname in PAIRS:
        major = next((m for m in majors if m.startswith(major_hint)), None)
        entry = creds.get(cname)
        if not major or not entry:
            report["pairs: not found"].append(f"{major_hint} + {cname}")
            continue
        label = f"{major} + {cname}"
        all_rows = program_rows(major)
        mtx = build_transcript(_filter_rows(all_rows, None, set(), None))[0]
        ctx, attested, _ = ccnt.minimal_transcript(entry, cc.to_requirement_rows(entry))
        known = {t["course_code"] for t in mtx}
        union = mtx + [t for t in ctx if t["course_code"] not in known]
        _, major_alone = audit(all_rows, None, None, mtx)
        _, major_both = audit(all_rows, None, None, union)
        user = {"credentials": [{"program": cname}]}
        att = {f"{cname}{ccnt._SEP}{g}": v for g, v in attested.items()}
        cred_alone = credentials_audit.audit_declared_credentials(user, ctx, None, att)[0]
        cred_both = credentials_audit.audit_declared_credentials(user, union, None, att)[0]
        if unsatisfied(major_both):
            report["pairs: major incomplete once credential courses added"].append(
                f"{label}: {unsatisfied(major_both)[:3]}")
        if [g["name"] for g in major_alone["groups"]] != [g["name"] for g in major_both["groups"]]:
            report["pairs: credential courses changed the major's option"].append(label)
        ca = [g["name"] for g in cred_alone["groups"] if not g["satisfied"]]
        cb = [g["name"] for g in cred_both["groups"] if not g["satisfied"]]
        if ca:
            report["pairs: credential incomplete on its own transcript"].append(f"{label}: {ca}")
        elif cb:
            report["pairs: credential incomplete once major courses added"].append(f"{label}: {cb}")
        report["_pairs_checked"].append(
            f"{label} (major {'ok' if not unsatisfied(major_both) else 'X'}, "
            f"credential {'ok' if not cb else 'X'})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--major")
    ap.add_argument("--pairs", action="store_true")
    a = ap.parse_args()
    majors = _load_all_programs()
    report = defaultdict(list)
    for name in majors:
        if a.major and a.major.lower() not in name.lower():
            continue
        all_rows = program_rows(name)
        invented_codes(name, all_rows, report)
        subplans = [None] + get_subplans(name)["subplans"]
        focuses = [None] + [f["name"] for f in focus_areas(name)]
        for sp in subplans:
            for fo in focuses:
                check_combo(name, all_rows, sp, fo, report)
    if a.pairs:
        check_pairs(majors, report)
    for k, v in sorted(report.items()):
        if k.startswith("_"):
            continue
        print(f"\n## {k} ({len(v)})")
        for line in v:
            print("  ", line)
    if a.pairs:
        print("\n## pairs checked")
        for line in report["_pairs_checked"]:
            print("  ", line)
    print(f"\nchecked {len(report['_checked'])} major/option/focus combinations end to end")


if __name__ == "__main__":
    main()
