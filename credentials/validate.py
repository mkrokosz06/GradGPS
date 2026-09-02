"""
Credential validation.

The goal is support for **every** University Park minor and certificate, so this draws a
hard line between two very different kinds of problem:

**Blockers** — the parse is structurally wrong, so an audit built on it would give the
student a false answer.  An unpaired `choose_one` row is the archetype: the engine reads
it as individually required (`audit_engine.py:1655`), which is what made
*Arts Entrepreneurship, Minor* demand 660 credits.  A credential with a blocker is
quarantined; there is no honest way to show it.

**Warnings** — the parse is faithful but incomplete or unusual: a credit total outside the
typical band, a course whose credits the bulletin doesn't state, or a requirement written
for a human ("in consultation with the minor adviser").  None of these make the audit
*wrong*; they make it *partial*.  The credential is supported and the gap is surfaced.

The distinction matters because the third category is not a data defect at all — PSU
genuinely defers those requirements to an adviser, so no scraper will ever resolve them.
Treating that as a failure would cap coverage at ~67% forever.  Treating it as a
student-attested slot (`unstructured_credits`, carrying the bulletin's own wording) is
both honest and complete: the app never claims the requirement is met on its own.
"""

from __future__ import annotations

# A PSU minor is typically 18-21 credits, certificates 9-18.  Deliberately loose, and
# only ever a warning — some credentials really are unusual, and the reconstruction
# widens whenever the bulletin states a range.
CREDIT_BAND = {
    "minor":       (12, 30),
    "certificate": (6, 30),
}

try:                                     # reuse the existing junk-title rule
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "scripts"))
    from fix_junk_titles import _is_junk  # type: ignore
except Exception:                        # pragma: no cover - keeps this module standalone
    def _is_junk(title):                 # type: ignore
        t = (title or "").strip()
        return bool(t) and t.replace(".", "").replace("-", "").isdigit()


def credit_range(groups: list[dict]) -> tuple[float, float]:
    """Reconstruct the credential's (min, max) credit total from its groups.

    A range rather than a number because the bulletin itself states ranges
    ("Select 2-7 credits", "HONOR 401 … 1-6").
    """
    # A section header that states its own credit total wins over summing its groups.
    # Some sections branch by student type ("Non-Geoscience Majors" / "Geoscience
    # Majors") and list every branch, so the sum double-counts what the student owes.
    lo = hi = 0.0
    declared: dict[str, tuple] = {}
    for g in groups:
        dmin, dmax = (g.get("section_credits") or (None, None))
        if dmin is not None:
            declared[g.get("section")] = (dmin, dmax or dmin)
    for dmin, dmax in declared.values():
        lo += dmin
        hi += dmax

    for g in groups:
        if g.get("section") in declared:
            continue
        gtype = g["group_type"]
        # A pool whose size the page never stated is a subdivision of the pool above
        # it ("Select Option A or B:" 9 cr, then "Select one of the following:" with a
        # blank credits cell), and its credits are already counted there.  This has to
        # be tested for EVERY pool type, not just the credit ones.
        if gtype in ("choose_credits", "choose_courses", "dept_credits",
                     "unstructured_credits") and not g.get("counts_toward_total", True):
            continue
        if gtype == "required":
            lo += sum(x["credits"] or 3 for x in g["courses"])
            hi += sum(x.get("credits_max") or x["credits"] or 3 for x in g["courses"])
        elif gtype == "choose_one":
            # One requirement per pair, valued at the pair's OWN credits — CourseLeaf
            # states them only on the chain's first row, and assuming 3 undercounted
            # every 4-credit alternative (CMPEN 270, "Digital Design", is 4).
            by_pair: dict = {}
            for x in g["courses"]:
                key = x["pair_group_id"] or f"single:{x['course_code']}"
                if x["credits"] is not None:
                    by_pair.setdefault(key, x["credits"])
                else:
                    by_pair.setdefault(key, None)
            c = sum(v if v is not None else 3 for v in by_pair.values())
            lo += c
            hi += c
        elif gtype == "choose_courses":
            c = (g["threshold"] or 0) * 3
            lo += c
            hi += c
        else:   # choose_credits / dept_credits / unstructured_credits
            # A pool whose size the page never stated is a subdivision of the pool
            # above it, and its credits are already counted there.
            if not g.get("counts_toward_total", True):
                continue
            lo += g["threshold"] or 0
            hi += g["threshold_max"] or g["threshold"] or 0
    return round(lo, 1), round(hi, 1)


def manual_credits(groups: list[dict]) -> float:
    """Credits the student must attest to, because the bulletin defers them to a human."""
    return round(sum(g["threshold"] or 0
                     for g in groups if g["group_type"] == "unstructured_credits"), 1)


def validate(entry: dict) -> tuple[list[str], list[str]]:
    """Return (blockers, warnings).  Empty blockers = supported."""
    blockers: list[str] = []
    warnings: list[str] = []
    groups = entry.get("groups") or []
    kind   = entry.get("kind", "minor")

    if not groups:
        return ["no requirement groups parsed"], []

    # ── BLOCKER: unpaired choose_one ─────────────────────────────────────────
    # Evaluated as individually required (audit_engine.py:1655).  After a
    # class-driven parse there should be none; a survivor means the page was
    # mis-shaped and the audit would over-require.
    for g in groups:
        if g["group_type"] == "choose_one":
            unpaired = [c["course_code"] for c in g["courses"] if not c["pair_group_id"]]
            if unpaired:
                blockers.append(
                    f"group '{g['name']}' has {len(unpaired)} unpaired choose_one row(s) "
                    f"(e.g. {', '.join(unpaired[:3])})"
                )

    # ── BLOCKER: a pool the engine cannot evaluate ───────────────────────────
    for g in groups:
        if g["group_type"] in ("choose_credits", "choose_courses"):
            if not g["courses"]:
                blockers.append(f"pool '{g['name']}' has no options")
            if g["threshold"] is None:
                blockers.append(f"pool '{g['name']}' has no threshold")
            elif g["threshold"] == 0 and not g["threshold_max"]:
                blockers.append(f"pool '{g['name']}' has a zero threshold")
        if g["group_type"] == "dept_credits":
            pool = g.get("pool") or {}
            if not (pool.get("dept") or pool.get("depts")):
                blockers.append(f"dept pool '{g['name']}' names no subject")
            if not g["threshold"]:
                blockers.append(f"dept pool '{g['name']}' has no threshold")

    # ── BLOCKER: junk titles ─────────────────────────────────────────────────
    # A credit count captured as a course title means the row itself was misread.
    # (A *blank* title is fine — the bulletin omits some, and the timeline backfills
    # them from the catalog via `_catalog_titles` in timeline.py.)
    junk = [c["course_code"] for g in groups for c in g["courses"]
            if c["course_title"].strip() and _is_junk(c["course_title"])]
    if junk:
        blockers.append(f"{len(junk)} junk course title(s) (e.g. {', '.join(junk[:3])})")

    # ── WARNING: requirements written for a human ────────────────────────────
    unstructured = [g for g in groups if g["group_type"] == "unstructured_credits"]
    if unstructured:
        warnings.append(
            f"{len(unstructured)} requirement(s) the student must confirm "
            f"({manual_credits(groups):g} cr), e.g. "
            f"\"{(unstructured[0].get('pool') or {}).get('text', '')[:70]}\""
        )

    # ── WARNING: credits the bulletin doesn't state ──────────────────────────
    # A pair alternative ("or ECON 102") legitimately carries no hours — CourseLeaf
    # puts the value only on the first row of an or-chain.
    for g in groups:
        if g["group_type"] in ("required", "choose_one"):
            credited_pairs = {c["pair_group_id"] for c in g["courses"]
                              if c["pair_group_id"] and c["credits"] is not None}
            missing = [c["course_code"] for c in g["courses"]
                       if c["credits"] is None and c["pair_group_id"] not in credited_pairs]
            if missing:
                warnings.append(
                    f"{len(missing)} course(s) in '{g['name']}' have no stated credits "
                    f"(e.g. {', '.join(missing[:3])}) — backfill from the catalog"
                )

    # ── WARNING: unusual credit total ────────────────────────────────────────
    lo, hi = credit_range(groups)
    band_lo, band_hi = CREDIT_BAND.get(kind, CREDIT_BAND["minor"])
    if hi < band_lo or lo > band_hi:
        warnings.append(
            f"credit total {lo:g}-{hi:g} is outside the typical {kind} band "
            f"{band_lo}-{band_hi} — worth an eyeball"
        )

    return blockers, warnings
