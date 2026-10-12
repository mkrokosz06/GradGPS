"""Invariant fuzzing of the audit engine over the real catalog.

    python scripts/fuzz_audit_invariants.py [--iters 2000] [--seed 1]

Needs the local catalog (docker-compose + load_catalog.py). Read-only.

Random transcripts are drawn from a program's own courses (plus gen-ed courses
and noise), then checked against rules that must hold for ANY transcript:

  order        shuffling transcript rows changes nothing
  add          adding a passed course never un-satisfies a requirement
  upgrade      in-progress -> done never un-satisfies a requirement
  grade        a better grade never un-satisfies a requirement
  failed       adding a failed course changes nothing
  transfer     transfer credit counts the same as a passed course
  counts       done + in_progress + missing == total
  gen-ed once  in the gen-ed audit, one transcript course fills at most one
               category (unless interdomain / writing)
  credential   (minors) credits counted never exceed the transcript's credits

Each failure is shrunk to a minimal transcript before it's printed.
"""
import argparse, copy, json, os, random, re, sys
from collections import defaultdict

BACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACK)
os.chdir(BACK)

from boto3.dynamodb.conditions import Key
from db import requirements_table
from audit_engine import run_audit, run_gen_ed_audit, _build_taken, _find_entry, GRADE_ORDER
from transcript_parser import _normalise_code
from routers.audit import _filter_rows, get_subplans
from routers.programs import _load_all_programs
import credential_catalog as cc
import credentials_audit

BULLETIN = json.load(open("scripts/bulletin_courses.json", encoding="utf-8"))
NOISE = [c for c in BULLETIN if not re.search(r"\d[A-Z]$", c)]


def rows_of(name):
    rows, kw = [], {"KeyConditionExpression": Key("program_name").eq(name)}
    while True:
        r = requirements_table.query(**kw)
        rows += r["Items"]
        if "LastEvaluatedKey" not in r:
            return rows
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def row(code, status, grade):
    code = code.strip().upper()
    info = BULLETIN.get(code) or BULLETIN.get(re.sub(r"(\d)[WHMN]$", r"\1", code)) or {}
    cr = float(info.get("credits") or 3)
    return {"course_code": _normalise_code(code), "status": status, "grade": grade,
            "credits_earned": 0.0 if status in ("in_progress", "failed") else cr,
            "is_writing": bool(re.search(r"\d[WMXY]$", code)), "raw_code": code}


def rand_tx(rng, codes, n):
    picks = rng.sample(codes, min(n, len(codes))) + rng.sample(NOISE, 3)
    tx, seen = [], set()
    for c in picks:
        r = rng.random()
        if r < 0.65:
            t = row(c, "done", rng.choice(["A", "A-", "B", "C", "C", "D", ""]))
        elif r < 0.8:
            t = row(c, "in_progress", "")
        elif r < 0.92:
            t = row(c, "transfer", "TR")
        else:
            t = row(c, "failed", "F")
        if t["course_code"] in seen:      # storage is keyed on course_code
            continue
        seen.add(t["course_code"])
        tx.append(t)
    return tx


def sat(res):
    out = set()
    for g in res["groups"]:
        if g.get("sub_groups"):
            for s in g["sub_groups"]:
                if s["satisfied"]:
                    out.add((g["name"], s["sub_type"], s["threshold"], s.get("pool_seq")))
        elif g["satisfied"]:
            out.add((g["name"],))
    return out


def canon(res):
    return json.dumps(res, sort_keys=True, default=str)


# ── invariants: each returns an error string or None ────────────────────────

def inv_order(f, tx, rng):
    t2 = tx[:]
    rng.shuffle(t2)
    if canon(f(tx)) != canon(f(t2)):
        a, b = sat(f(tx)), sat(f(t2))
        return f"shuffle changed result (satisfied diff: {sorted(map(str, a ^ b))[:3]})"


def inv_add(f, tx, rng, pool):
    base = sat(f(tx))
    have = {t["course_code"] for t in tx}
    for c in rng.sample(pool, min(6, len(pool))):
        r = row(c, "done", "A")
        if r["course_code"] in have:
            continue
        lost = base - sat(f(tx + [r]))
        if lost:
            return f"adding passed {c} un-satisfied {sorted(map(str, lost))[:2]}"


def inv_upgrade(f, tx, rng):
    base = sat(f(tx))
    for i, t in enumerate(tx):
        if t["status"] == "in_progress":
            t2 = copy.deepcopy(tx)
            t2[i] = row(t["raw_code"], "done", "A")
            lost = base - sat(f(t2))
            if lost:
                return f"finishing {t['raw_code']} un-satisfied {sorted(map(str, lost))[:2]}"


def inv_grade(f, tx, rng):
    base = sat(f(tx))
    for i, t in enumerate(tx):
        if t["status"] == "done" and t["grade"] in GRADE_ORDER and t["grade"] != "A":
            t2 = copy.deepcopy(tx)
            t2[i]["grade"] = "A"
            lost = base - sat(f(t2))
            if lost:
                return f"raising {t['raw_code']} to A un-satisfied {sorted(map(str, lost))[:2]}"


def inv_failed(f, tx, rng, pool):
    have = {t["course_code"] for t in tx}
    for c in rng.sample(pool, min(4, len(pool))):
        r = row(c, "failed", "F")
        if r["course_code"] in have:
            continue
        if sat(f(tx)) != sat(f(tx + [r])):
            return f"adding FAILED {c} changed what's satisfied"


def inv_transfer(f, tx, rng):
    for i, t in enumerate(tx):
        if t["status"] == "done" and t["grade"] in ("A", ""):
            t2 = copy.deepcopy(tx)
            t2[i]["status"], t2[i]["grade"] = "transfer", "TR"
            if sat(f(tx)) != sat(f(t2)):
                return f"{t['raw_code']} as transfer differs from passed"


def inv_counts(f, tx, rng):
    r = f(tx)
    if r["done"] + r["in_progress"] + r["missing"] != r["total"]:
        return f"done+ip+missing != total ({r['done']}+{r['in_progress']}+{r['missing']} vs {r['total']})"
    for g in r["groups"]:
        if g["group_type"] == "required" and g["satisfied"] and any(
                i["status"] != "done" for i in g["items"]):
            return f"required group '{g['name']}' satisfied with an unfinished item"


def inv_gened_once(f, tx, rng):
    res = f(tx)
    taken = _build_taken(tx)
    used = defaultdict(set)
    for g in res["groups"]:
        if g["group_type"] == "writing_intensive":
            continue
        for it in g["items"]:
            if it.get("status") not in ("done", "in_progress") or it.get("multi_category"):
                continue
            e = _find_entry(it["course_code"], taken)
            if e is not None and not it.get("duplicate"):
                used[id(e)].add(g["name"])
    for eid, groups in used.items():
        if len(groups) > 1:
            code = next(t["raw_code"] for t in tx
                        if _find_entry(t["course_code"], taken) is not None
                        and id(_find_entry(t["course_code"], taken)) == eid)
            return f"one course ({code}) counted in {len(groups)} gen-ed categories: {sorted(groups)[:3]}"


def inv_cred_credits(f, tx, rng):
    r = f(tx)
    total = sum(t["credits_earned"] for t in tx if t["status"] in ("done", "transfer"))
    if r.get("credits_counted", 0) > total + 0.01:
        return f"credits_counted {r['credits_counted']} > transcript {total}"


def shrink(check, tx):
    """Drop rows while the failure persists (deterministic RNG per attempt)."""
    i = 0
    while i < len(tx):
        t2 = tx[:i] + tx[i + 1:]
        if check(t2):
            tx = t2
        else:
            i += 1
    return tx


def run_target(label, f, codes, rng, iters, invariants, report):
    if not codes:
        return
    for it in range(iters):
        tx = rand_tx(rng, codes, rng.randint(min(3, len(codes)), min(40, len(codes))))
        for name, inv, needs_pool in invariants:
            seed = rng.random()
            args = (codes,) if needs_pool else ()
            def check(t, inv=inv, args=args, seed=seed):
                try:
                    return inv(f, t, random.Random(seed), *args)
                except Exception as e:     # a crash is a finding too
                    return f"CRASH {type(e).__name__}: {e}"
            err = check(tx)
            if err:
                key = (name, label)
                if key in report:
                    continue
                small = shrink(lambda t: bool(check(t)), tx)
                report[key] = (check(small) or err,
                               [f"{t['raw_code']}:{t['status']}:{t['grade']}" for t in small])
                print(f"FAIL [{name}] {label}: {report[key][0]} | {report[key][1]}", flush=True)


COMMON = [("order", inv_order, False), ("add", inv_add, True), ("upgrade", inv_upgrade, False),
          ("grade", inv_grade, False), ("failed", inv_failed, True),
          ("transfer", inv_transfer, False), ("counts", inv_counts, False)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=40, help="random transcripts per program")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--programs", type=int, default=0, help="limit majors (0 = all)")
    ap.add_argument("--only", choices=["gened", "majors", "creds"], action="append")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    report = {}

    only = set(a.only or ["gened", "majors", "creds"])
    gen_rows = rows_of("__GEN_ED__")
    gen_codes = sorted({r["course_code"] for r in gen_rows if r.get("course_code")})
    if "gened" in only:
      run_target("__GEN_ED__", lambda t: run_gen_ed_audit(gen_rows, t), gen_codes, rng,
               max(4, a.iters // 4), COMMON + [("gen-ed once", inv_gened_once, False)], report)

    majors = _load_all_programs() if "majors" in only else []
    if a.programs:
        majors = rng.sample(majors, a.programs)
    print(f"gen-ed done ({len(report)} failures so far)", flush=True)
    for k, m in enumerate(majors):
        if k % 25 == 0:
            print(f"majors {k}/{len(majors)} ({len(report)} failures so far)", flush=True)
        all_rows = rows_of(m)
        subs = get_subplans(m)["subplans"]
        sp = rng.choice(subs) if subs and rng.random() < 0.6 else None
        rows = _filter_rows(all_rows, sp, set(), None)
        codes = sorted({r["course_code"] for r in rows if r.get("course_code")})
        run_target(m + (f" / {sp}" if sp else ""), lambda t, rows=rows: run_audit(rows, t),
                   codes + rng.sample(gen_codes, 10), rng, a.iters, COMMON, report)

    for name, entry in (sorted(cc._catalog().items()) if "creds" in only else []):
        user = {"credentials": [{"program": name}]}
        f = lambda t, user=user: credentials_audit.audit_declared_credentials(user, t)[0]
        codes = sorted({c["course_code"] for g in entry["groups"] for c in g.get("courses", [])})
        # dept pools have no list: add bulletin courses from the subjects they name
        depts = {d for g in entry["groups"] for p in [g.get("pool") or {}]
                 for d in (p.get("depts") or []) + ([p["dept"]] if p.get("dept") else [])}
        codes += [c for c in NOISE if c.split()[0] in depts][:40]
        run_target(name, f, codes, rng, max(5, a.iters // 4),
                   COMMON + [("credential credits", inv_cred_credits, False)], report)

    by_inv = defaultdict(list)
    for (inv, label), (err, small) in report.items():
        by_inv[inv].append((label, err, small))
    for inv, items in sorted(by_inv.items()):
        print(f"\n## {inv} ({len(items)} programs)")
        for label, err, small in items[:25]:
            print(f"   {label}\n      {err}\n      minimal transcript: {small}")
        if len(items) > 25:
            print(f"   ... {len(items) - 25} more")
    print(f"\n{len(report)} invariant failures")


if __name__ == "__main__":
    main()
