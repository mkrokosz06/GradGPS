"""
Audit engine.
Takes a student's completed courses + a major's requirement rows
and returns a structured audit result.
"""

import re
from decimal import Decimal
from collections import defaultdict


GRADE_ORDER = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"]

# PSU course equivalences — confirmed cross-listings and prefix renames.
# Each tuple is (code_a, code_b) where both codes refer to identical content.
# Bidirectional: taking either satisfies a requirement for either.
# Sources: bulletin.psu.edu PDFs + official IST advising document (Fall 2025).
#
# DO NOT add prefix-level (all-number) aliases for CRIM/CRIMJ — they are
# separate departments (Criminology vs Criminal Justice) that only share
# specific cross-listed sections. Only confirmed course-by-course pairs below.
_EQUIVALENCE_PAIRS: list[tuple[str, str]] = [
    # ── CRIM ↔ CRIMJ confirmed cross-listings ────────────────────────────────
    # Same section registered under both prefixes. Confirmed from bulletin PDFs.
    ("CRIM 12",  "CRIMJ 12"),
    ("CRIM 100", "CRIMJ 100"),
    ("CRIM 113", "CRIMJ 113"),
    ("CRIM 204", "CRIMJ 204"),
    ("CRIM 406", "CRIMJ 406"),
    ("CRIM 412", "CRIMJ 412"),
    ("CRIM 413", "CRIMJ 413"),
    ("CRIM 421", "CRIMJ 421"),
    ("CRIM 422", "CRIMJ 422"),
    ("CRIM 423", "CRIMJ 423"),
    ("CRIM 424", "CRIMJ 424"),
    ("CRIM 425", "CRIMJ 425"),
    ("CRIM 441", "CRIMJ 441"),
    ("CRIM 451", "CRIMJ 451"),
    ("CRIM 453", "CRIMJ 453"),
    ("CRIM 459", "CRIMJ 459"),
    ("CRIM 467", "CRIMJ 467"),
    ("CRIM 482", "CRIMJ 482"),
    # ── IST → ETI renames (effective Fall 2025) ──────────────────────────────
    # Official IST advising doc: "course content has not changed; ONLY the prefix."
    ("IST 301", "ETI 301"),
    ("IST 302", "ETI 302"),
    ("IST 420", "ETI 420"),
    ("IST 421", "ETI 421"),
    # ── IST → HCDD renames (effective Fall 2025) ─────────────────────────────
    ("IST 311", "HCDD 311"),
    ("IST 331", "HCDD 331"),
    ("IST 411", "HCDD 411"),
    ("IST 412", "HCDD 412"),
    ("IST 413", "HCDD 413"),
    ("IST 446", "HCDD 446"),
    # ── IST → CYBER renames (effective Fall 2025) ────────────────────────────
    ("IST 451", "CYBER 451"),
    ("IST 454", "CYBER 454"),
    ("IST 456", "CYBER 456"),
    # ── SRA → CYBER rename (effective Fall 2025) ─────────────────────────────
    ("SRA 221", "CYBER 221"),
]

# Build bidirectional lookup at module load: code → [equivalent codes]
_COURSE_ALIASES: dict[str, list[str]] = {}
for _a, _b in _EQUIVALENCE_PAIRS:
    _COURSE_ALIASES.setdefault(_a, []).append(_b)
    _COURSE_ALIASES.setdefault(_b, []).append(_a)


def _build_taken(transcript_courses: list[dict]) -> dict:
    """
    Build taken lookup from transcript, including confirmed course equivalences.
    Cross-listed courses (CRIM/CRIMJ) and renamed prefixes (IST→ETI/HCDD/CYBER)
    are registered under all equivalent codes so the audit matches correctly.
    """
    taken: dict = {}
    for c in transcript_courses:
        code = c["course_code"].strip().upper()
        entry = {
            "status":         c.get("status", "done"),
            "grade":          c.get("grade", ""),
            "credits_earned": float(c.get("credits_earned", 0)),
        }
        taken[code] = entry
        for alias in _COURSE_ALIASES.get(code, []):
            taken.setdefault(alias, entry)
    return taken


def _grade_meets(earned_grade: str, min_grade: str) -> bool:
    """Returns True if earned_grade >= min_grade (A is highest)."""
    if not min_grade or not earned_grade:
        return True
    try:
        return GRADE_ORDER.index(earned_grade) <= GRADE_ORDER.index(min_grade)
    except ValueError:
        return True   # unknown grade format — don't block


def run_gen_ed_audit(requirement_rows: list[dict], transcript_courses: list[dict]) -> dict:
    """
    Like run_audit, but enforces cross-group course exclusivity for gen ed:
    once a course is consumed to satisfy one group it cannot satisfy another.

    Processing order (so required courses are claimed first):
      1. required / choose_one  groups
      2. choose_credits / choose_courses pools
    """
    # Build taken lookup (includes department prefix aliases)
    taken = _build_taken(transcript_courses)

    # Group rows by section
    groups_map: dict[str, list[dict]] = defaultdict(list)
    group_meta: dict[str, dict] = {}
    for row in requirement_rows:
        g = row.get("requirement_group", "General Requirements")
        groups_map[g].append(row)
        if g not in group_meta:
            group_meta[g] = {
                "group_type":      row.get("group_type", "required"),
                "group_threshold": int(row["group_threshold"]) if row.get("group_threshold") else None,
            }

    # Sort groups: required/choose_one first so they claim courses before pools
    PRIORITY = {"required": 0, "choose_one": 1, "choose_credits": 2, "choose_courses": 3}
    ordered_groups = sorted(
        groups_map.items(),
        key=lambda kv: PRIORITY.get(group_meta[kv[0]]["group_type"], 99)
    )

    consumed: set[str] = set()   # course codes already claimed by an earlier group

    group_results = []
    total_done = total_ip = total_missing = 0
    total_credits = 0.0

    for group_name, rows in ordered_groups:
        gtype     = group_meta[group_name]["group_type"]
        threshold = group_meta[group_name]["group_threshold"]

        result = _eval_type_exclusive(gtype, rows, taken, threshold, consumed)

        # Mark courses this group consumed so later groups can't reuse them.
        # multi_category courses (interdomain / US / IL dual-designated) are
        # intentionally exempt — they satisfy two categories simultaneously.
        for item in result["items"]:
            if item.get("status") in ("done", "in_progress") and not item.get("multi_category"):
                consumed.add(item["course_code"])

        d, ip, m = _pool_counts(gtype, result)
        total_done    += d
        total_ip      += ip
        total_missing += m
        total_credits += result.get("credits_earned", 0.0)

        group_results.append({
            "name":           group_name,
            "group_type":     gtype,
            "threshold":      threshold,
            "satisfied":      result["satisfied"],
            "done":           result["done"],
            "in_progress":    result["in_progress"],
            "missing":        result["missing"],
            "credits_earned": result.get("credits_earned", 0.0),
            "items":          result["items"],
        })

    program = requirement_rows[0]["program_name"] if requirement_rows else "__GEN_ED__"
    return {
        "major":          program,
        "total":          total_done + total_ip + total_missing,
        "done":           total_done,
        "in_progress":    total_ip,
        "missing":        total_missing,
        "credits_earned": round(total_credits, 1),
        "groups":         group_results,
    }


def run_audit(requirement_rows: list[dict], transcript_courses: list[dict]) -> dict:
    """
    Parameters
    ----------
    requirement_rows : list of dicts from DynamoDB requirements table
        Keys: program_name, requirement_group, group_type, group_threshold,
              course_code, credits, min_grade, pair_group_id, ...

    transcript_courses : list of dicts from transcript parser / DynamoDB
        Keys: course_code, grade, credits_earned, status (done/in_progress/transfer)

    Returns
    -------
    dict with keys:
        major           str
        total           int
        done            int
        in_progress     int
        missing         int
        credits_earned  float
        groups          list of group result dicts
    """

    # ── Build lookup from student transcript ──────────────────────────────────
    # course_code → {"status": ..., "grade": ..., "credits_earned": ...}
    # Includes department prefix aliases (e.g. CRIMJ -> CRIM)
    taken = _build_taken(transcript_courses)

    # ── Group requirement rows by section ────────────────────────────────────
    # Preserve insertion order (rows come sorted by group_course SK from DynamoDB)
    groups_map: dict[str, list[dict]] = defaultdict(list)
    group_meta: dict[str, dict]       = {}

    for row in requirement_rows:
        g = row.get("requirement_group", "General Requirements")
        groups_map[g].append(row)
        if g not in group_meta:
            group_meta[g] = {
                "group_type":      row.get("group_type", "required"),
                "group_threshold": int(row["group_threshold"]) if row.get("group_threshold") else None,
            }

    # ── Evaluate each group ──────────────────────────────────────────────────
    group_results = []
    total_done = total_ip = total_missing = 0
    total_credits = 0.0

    for group_name, rows in groups_map.items():
        # A group may contain rows with different group_types (e.g. ETI Requirements
        # has both choose_one and choose_credits rows). Split and evaluate each
        # sub-type separately, then merge into one group result.
        type_buckets: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            type_buckets[row.get("group_type", "required")].append(row)

        if len(type_buckets) == 1:
            # Homogeneous — simple path
            gtype     = next(iter(type_buckets))
            threshold = group_meta[group_name]["group_threshold"]
            result    = _eval_type(gtype, rows, taken, threshold)

            d, ip, m = _pool_counts(gtype, result)
            total_done    += d
            total_ip      += ip
            total_missing += m
            total_credits += result.get("credits_earned", 0.0)

            group_results.append({
                "name":           group_name,
                "group_type":     gtype,
                "threshold":      threshold,
                "satisfied":      result["satisfied"],
                "done":           result["done"],
                "in_progress":    result["in_progress"],
                "missing":        result["missing"],
                "credits_earned": result.get("credits_earned", 0.0),
                "items":          result["items"],
            })

        else:
            # Mixed types — evaluate sub-buckets and combine into sub-groups
            sub_results = []
            agg_done = agg_ip = agg_missing = 0
            agg_credits = 0.0

            for gtype, bucket_rows in type_buckets.items():
                # Threshold for choose_credits rows is stored per-row; use the first
                thr = None
                if gtype in ("choose_credits", "choose_courses"):
                    for r in bucket_rows:
                        if r.get("group_threshold"):
                            thr = int(r["group_threshold"])
                            break

                res = _eval_type(gtype, bucket_rows, taken, thr)
                d, ip, m = _pool_counts(gtype, res)
                agg_done    += d
                agg_ip      += ip
                agg_missing += m
                agg_credits += res.get("credits_earned", 0.0)
                sub_results.append({
                    "sub_type":       gtype,
                    "threshold":      thr,
                    "satisfied":      res["satisfied"],
                    "done":           res["done"],
                    "in_progress":    res["in_progress"],
                    "missing":        res["missing"],
                    "credits_earned": res.get("credits_earned", 0.0),
                    "items":          res["items"],
                })

            total_done    += agg_done
            total_ip      += agg_ip
            total_missing += agg_missing
            total_credits += agg_credits

            group_results.append({
                "name":           group_name,
                "group_type":     "mixed",
                "threshold":      None,
                "satisfied":      all(s["satisfied"] for s in sub_results),
                "done":           agg_done,
                "in_progress":    agg_ip,
                "missing":        agg_missing,
                "credits_earned": round(agg_credits, 1),
                "sub_groups":     sub_results,
                # Flatten items for backwards-compat
                "items":          [item for s in sub_results for item in s["items"]],
            })

    major = requirement_rows[0]["program_name"] if requirement_rows else "Unknown"

    return {
        "major":          major,
        "total":          total_done + total_ip + total_missing,
        "done":           total_done,
        "in_progress":    total_ip,
        "missing":        total_missing,
        "credits_earned": round(total_credits, 1),
        "groups":         group_results,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pool_counts(gtype: str, result: dict) -> tuple[int, int, int]:
    """
    Return (done, in_progress, missing) contribution to the global totals.

    For choose_credits / choose_courses pools, each pool counts as a SINGLE
    requirement slot — not one slot per pool item.  This prevents inflating
    the "missing" count with unchosen electives from a satisfied pool.
    """
    if gtype in ("choose_credits", "choose_courses"):
        if result["satisfied"]:
            return 1, 0, 0
        elif result["in_progress"] > 0:
            return 0, 1, 0
        else:
            return 0, 0, 1
    # required / choose_one: individual item counts are already accurate
    return result["done"], result["in_progress"], result["missing"]


# ── Exclusive dispatch helper (gen ed — cross-group course consumption) ──────

def _eval_type_exclusive(
    gtype: str, rows: list[dict], taken: dict, threshold, consumed: set[str]
) -> dict:
    """
    Same as _eval_type but skips courses already consumed by a previous group.
    A course is considered "available" only if its normalised code is not in consumed.
    """
    available_rows = []
    for row in rows:
        code = row.get("course_code", "").strip().upper()
        # Also check W-stripped and variant-suffix forms (mirrors _course_status logic)
        w_stripped = re.sub(r"[WHN]$", "", code)
        variant    = next(
            (k for k in taken if k.startswith(code) and len(k) == len(code) + 1 and k[-1].isalpha()),
            None,
        )
        actual_code = variant or (w_stripped if w_stripped in taken else code)
        # multi_category courses (interdomain / US+domain dual-designated) are
        # never blocked by the consumed set — they can satisfy two groups at once.
        if actual_code in consumed and not row.get("multi_category"):
            available_rows.append({**row, "_consumed": True})
        else:
            available_rows.append(row)

    return _eval_type_with_consumed(gtype, available_rows, taken, threshold)


def _eval_type_with_consumed(gtype: str, rows: list[dict], taken: dict, threshold) -> dict:
    """Like _eval_type but rows may carry _consumed=True to force-missing status."""
    if gtype == "required":
        return _eval_required_consumed(rows, taken)
    elif gtype == "choose_one":
        return _eval_choose_one_consumed(rows, taken)
    elif gtype == "choose_credits":
        return _eval_choose_credits_consumed(rows, taken, threshold)
    elif gtype == "choose_courses":
        return _eval_choose_courses_consumed(rows, taken, threshold)
    else:
        return _eval_required_consumed(rows, taken)


def _course_status_consumed(row: dict, taken: dict) -> str:
    """Like _course_status but returns 'consumed' when row has _consumed=True."""
    if row.get("_consumed"):
        return "consumed"
    return _course_status(row, taken)


def _eval_required_consumed(rows: list[dict], taken: dict) -> dict:
    items = []
    done = ip = missing = 0
    credits_earned = 0.0
    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        item = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "min_grade":    row.get("min_grade", ""),
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            item["multi_category"] = True
        items.append(item)
    return {"satisfied": missing == 0 and ip == 0, "done": done, "in_progress": ip,
            "missing": missing, "credits_earned": credits_earned, "items": items}


def _eval_choose_one_consumed(rows: list[dict], taken: dict) -> dict:
    pairs: dict = defaultdict(list)
    unpaired = []
    for row in rows:
        pid = row.get("pair_group_id")
        if pid:
            pairs[str(pid)].append(row)
        else:
            unpaired.append(row)

    items = []
    done = ip = missing = 0
    credits_earned = 0.0

    for pid, pair_rows in pairs.items():
        pair_status  = "missing"
        best_credits = 0.0
        best_code    = ""

        for row in pair_rows:
            code   = row.get("course_code", "").strip().upper()
            status = _course_status_consumed(row, taken)
            if status == "done" and pair_status != "done":
                pair_status  = "done"
                best_code    = code
                best_credits = taken.get(code, {}).get("credits_earned", 0)
            elif status == "in_progress" and pair_status == "missing":
                pair_status = "in_progress"
                best_code   = code

        if pair_status == "done":
            done += 1
            credits_earned += best_credits
        elif pair_status == "in_progress":
            ip += 1
        else:
            missing += 1

        for row in pair_rows:
            code = row.get("course_code", "").strip().upper()
            pitem = {
                "course_code":   code,
                "course_title":  row.get("course_title", ""),
                "credits":       float(row["credits"]) if row.get("credits") else None,
                "min_grade":     row.get("min_grade", ""),
                "status":        _course_status_consumed(row, taken),
                "grade":         taken.get(code, {}).get("grade", ""),
                "pair_group_id": pid,
                "pair_status":   pair_status,
            }
            if row.get("multi_category"):
                pitem["multi_category"] = True
            items.append(pitem)

    for row in unpaired:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        uitem = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            uitem["multi_category"] = True
        items.append(uitem)

    return {"satisfied": missing == 0 and ip == 0, "done": done, "in_progress": ip,
            "missing": missing, "credits_earned": credits_earned, "items": items}


def _eval_choose_credits_consumed(rows: list[dict], taken: dict, threshold) -> dict:
    items = []
    credits_earned = 0.0
    done = ip = missing = 0
    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        cr     = float(row["credits"]) if row.get("credits") else 0.0
        if status == "done":
            credits_earned += taken.get(code, {}).get("credits_earned", cr)
            done += 1
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        citem = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      cr,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            citem["multi_category"] = True
        items.append(citem)
    credits_needed = max(0, (threshold or 0) - credits_earned)
    satisfied = (threshold is None) or (credits_earned >= threshold)
    return {"satisfied": satisfied, "credits_earned": round(credits_earned, 1),
            "credits_needed": round(credits_needed, 1), "threshold": threshold,
            "done": done, "in_progress": ip, "missing": missing, "items": items}


def _eval_choose_courses_consumed(rows: list[dict], taken: dict, threshold) -> dict:
    items = []
    done = ip = missing = 0
    credits_earned = 0.0
    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status_consumed(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        ccitem = {
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        }
        if row.get("multi_category"):
            ccitem["multi_category"] = True
        items.append(ccitem)
    courses_needed = max(0, (threshold or 0) - done)
    satisfied = (threshold is None) or (done >= threshold)
    return {"satisfied": satisfied, "courses_needed": courses_needed, "threshold": threshold,
            "done": done, "in_progress": ip, "missing": missing,
            "credits_earned": credits_earned, "items": items}


# ── Dispatch helper ─────────────────────────────────────────────────────────

def _eval_type(gtype: str, rows: list[dict], taken: dict, threshold) -> dict:
    if gtype == "required":
        return _eval_required(rows, taken)
    elif gtype == "choose_one":
        return _eval_choose_one(rows, taken)
    elif gtype == "choose_credits":
        return _eval_choose_credits(rows, taken, threshold)
    elif gtype == "choose_courses":
        return _eval_choose_courses(rows, taken, threshold)
    else:
        return _eval_required(rows, taken)   # fallback


# ── Group type evaluators ────────────────────────────────────────────────────

def _course_status(row: dict, taken: dict) -> str:
    """Returns "done", "in_progress", or "missing" for a single course row."""
    code      = row.get("course_code", "").strip().upper()
    min_grade = row.get("min_grade", "")
    # Try matches in order of specificity:
    #  1. Exact: "CAS 100" → "CAS 100"
    #  2. W-stripped: catalog "IST 440W" → transcript "IST 440"
    #     (transcript_parser normalises trailing W from transcript codes)
    #  3. Variant suffix: catalog "CAS 100" → transcript "CAS 100C"
    #     (PSU uses CAS 100A/B/C as variants that all satisfy CAS 100 requirement)
    entry = (
        taken.get(code)
        or taken.get(re.sub(r"[WHN]$", "", code))
        or next(
            (v for k, v in taken.items()
             if k.startswith(code) and len(k) == len(code) + 1 and k[-1].isalpha()),
            None,
        )
    )

    if not entry:
        return "missing"

    if entry["status"] == "in_progress":
        return "in_progress"

    if entry["status"] in ("done", "transfer"):
        if _grade_meets(entry.get("grade", ""), min_grade):
            return "done"
        else:
            return "missing"   # grade too low — still counts as missing

    return "missing"


def _eval_required(rows: list[dict], taken: dict) -> dict:
    """Every course must be completed."""
    items = []
    done = ip = missing = 0
    credits_earned = 0.0

    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)

        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1

        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "min_grade":    row.get("min_grade", ""),
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    return {
        "satisfied":     missing == 0 and ip == 0,
        "done":          done,
        "in_progress":   ip,
        "missing":       missing,
        "credits_earned": credits_earned,
        "items":         items,
    }


def _eval_choose_one(rows: list[dict], taken: dict) -> dict:
    """
    Courses sharing a pair_group_id are alternatives — need at least one per pair.
    Courses without a pair_group_id are treated as individually required (rare).
    """
    # Group by pair_group_id
    pairs: dict = defaultdict(list)
    unpaired = []

    for row in rows:
        pid = row.get("pair_group_id")
        if pid:
            pairs[str(pid)].append(row)
        else:
            unpaired.append(row)

    items  = []
    done   = ip = missing = 0
    credits_earned = 0.0

    # Each pair counts as ONE requirement — satisfied if any course in it is done/ip
    for pid, pair_rows in pairs.items():
        pair_status = "missing"
        best_grade  = ""
        best_code   = ""
        best_credits = 0.0

        for row in pair_rows:
            code   = row.get("course_code", "").strip().upper()
            status = _course_status(row, taken)
            if status == "done" and pair_status != "done":
                pair_status  = "done"
                best_grade   = taken.get(code, {}).get("grade", "")
                best_code    = code
                best_credits = taken.get(code, {}).get("credits_earned", 0)
            elif status == "in_progress" and pair_status == "missing":
                pair_status = "in_progress"
                best_code   = code

        if pair_status == "done":
            done += 1
            credits_earned += best_credits
        elif pair_status == "in_progress":
            ip += 1
        else:
            missing += 1

        # Add all courses in the pair to items, mark the satisfied one
        for row in pair_rows:
            code = row.get("course_code", "").strip().upper()
            items.append({
                "course_code":   code,
                "course_title":  row.get("course_title", ""),
                "credits":       float(row["credits"]) if row.get("credits") else None,
                "min_grade":     row.get("min_grade", ""),
                "status":        _course_status(row, taken),
                "grade":         taken.get(code, {}).get("grade", ""),
                "pair_group_id": pid,
                "pair_status":   pair_status,   # overall pair outcome
            })

    # Handle unpaired rows as required
    for row in unpaired:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)
        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1
        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    return {
        "satisfied":      missing == 0 and ip == 0,
        "done":           done,
        "in_progress":    ip,
        "missing":        missing,
        "credits_earned": credits_earned,
        "items":          items,
    }


def _eval_choose_credits(rows: list[dict], taken: dict, threshold: int | None) -> dict:
    """Sum credits of completed pool courses; satisfied when >= threshold."""
    items          = []
    credits_earned = 0.0
    done = ip = missing = 0

    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)
        cr     = float(row["credits"]) if row.get("credits") else 0.0

        if status == "done":
            credits_earned += taken.get(code, {}).get("credits_earned", cr)
            done += 1
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1

        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      cr,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    credits_needed = max(0, (threshold or 0) - credits_earned)
    satisfied = (threshold is None) or (credits_earned >= threshold)

    return {
        "satisfied":       satisfied,
        "credits_earned":  round(credits_earned, 1),
        "credits_needed":  round(credits_needed, 1),
        "threshold":       threshold,
        "done":            done,
        "in_progress":     ip,
        "missing":         missing,
        "items":           items,
    }


def _eval_choose_courses(rows: list[dict], taken: dict, threshold: int | None) -> dict:
    """Count completed pool courses; satisfied when count >= threshold."""
    items = []
    done = ip = missing = 0
    credits_earned = 0.0

    for row in rows:
        code   = row.get("course_code", "").strip().upper()
        status = _course_status(row, taken)

        if status == "done":
            done += 1
            credits_earned += taken.get(code, {}).get("credits_earned", 0)
        elif status == "in_progress":
            ip += 1
        else:
            missing += 1

        items.append({
            "course_code":  code,
            "course_title": row.get("course_title", ""),
            "credits":      float(row["credits"]) if row.get("credits") else None,
            "status":       status,
            "grade":        taken.get(code, {}).get("grade", ""),
        })

    courses_needed = max(0, (threshold or 0) - done)
    satisfied = (threshold is None) or (done >= threshold)

    return {
        "satisfied":      satisfied,
        "courses_needed": courses_needed,
        "threshold":      threshold,
        "done":           done,
        "in_progress":    ip,
        "missing":        missing,
        "credits_earned": credits_earned,
        "items":          items,
    }
