"""
Tests for attempt precedence: when several transcript entries could answer one
requirement code (the real row, a cross-listing / rename alias, a suffix-stripped
form, an honors fill, a section-letter variant), the audit uses the BEST attempt
-- passed > in progress > failed -- whatever order the transcript rows come in.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_attempt_precedence.py -v
  * plain python:  cd backend && python tests/test_attempt_precedence.py

Hermetic -- audit engine only, no DynamoDB.

The bug: `_build_taken()` kept the first entry registered under a code
(setdefault) and `_find_entry()` returned the first section-letter variant in
dict order, so a failed CAS 100A hid a passed CAS 100B. Prod returns transcript
rows sorted by course_code, so the failing order is the one students got.
Also: Writing Across the Curriculum ignored writing-flagged transfer credit.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_engine import run_audit, run_gen_ed_audit


def _req(code, group="G", gtype="required", **extra):
    return {"program_name": "X", "requirement_group": group,
            "group_type": gtype, "course_code": code, **extra}


def _tx(code, status="done", grade="A", credits=3, **extra):
    return {"course_code": code, "status": status, "grade": grade,
            "credits_earned": credits, **extra}


def _fail(code):
    return _tx(code, status="failed", grade="F", credits=0)


def _satisfied(result, group="G"):
    return next(g for g in result["groups"] if g["name"] == group)["satisfied"]


def _both_orders(rows, a, b):
    return _satisfied(run_audit(rows, [a, b])), _satisfied(run_audit(rows, [b, a]))


# ── Section-letter variant ───────────────────────────────────────────────────

def test_failed_variant_does_not_hide_passed_variant():
    rows = [_req("CAS 100")]
    a = _fail("CAS 100A")
    b = _tx("CAS 100B", grade="B")
    assert _both_orders(rows, a, b) == (True, True)


def test_failed_exact_does_not_hide_passed_variant():
    rows = [_req("CAS 100")]
    assert _both_orders(rows, _fail("CAS 100"), _tx("CAS 100C")) == (True, True)


def test_in_progress_variant_beats_failed_variant():
    rows = [_req("CAS 100")]
    for order in ([_fail("CAS 100A"), _tx("CAS 100B", status="in_progress", grade="")],
                  [_tx("CAS 100B", status="in_progress", grade=""), _fail("CAS 100A")]):
        g = run_audit(rows, order)["groups"][0]
        assert g["in_progress"] == 1 and g["missing"] == 0


def test_better_grade_variant_meets_min_grade():
    rows = [_req("CAS 100", min_grade="C")]
    assert _both_orders(rows, _tx("CAS 100A", grade="D"), _tx("CAS 100B", grade="C")) == (True, True)


# ── Cross-listing / rename aliases ───────────────────────────────────────────

def test_failed_real_row_does_not_block_passed_cross_listing():
    # HDFS 258N is cross-listed with CMAS 258N.
    rows = [_req("CMAS 258N")]
    assert _both_orders(rows, _fail("CMAS 258"), _tx("HDFS 258")) == (True, True)


def test_failed_rename_alias_does_not_hide_passed_course():
    rows = [_req("ETI 301")]
    assert _both_orders(rows, _fail("ETI 301"), _tx("IST 301")) == (True, True)
    rows = [_req("IST 301")]
    assert _both_orders(rows, _tx("ETI 301"), _fail("IST 301")) == (True, True)


def test_tied_aliases_resolve_independent_of_order():
    # SOC 103 is an alias of both AFAM 103 and WMNST 103; two equal passes must
    # resolve to the same one whichever row comes first (else a pool flags a
    # different item as the duplicate on each shuffle).
    from audit_engine import _build_taken
    a, b = _tx("AFAM 103", grade="C"), _tx("WMNST 103", grade="C", credits=4)
    assert (_build_taken([a, b])["SOC 103"]["credits_earned"]
            == _build_taken([b, a])["SOC 103"]["credits_earned"] == 3)


def test_failed_only_stays_missing():
    for rows, tx in (([_req("CAS 100")], [_fail("CAS 100A"), _fail("CAS 100B")]),
                     ([_req("CMAS 258N")], [_fail("CMAS 258"), _fail("HDFS 258")]),
                     ([_req("ENGL 15")], [_fail("ENGL 137"), _fail("CAS 137")])):
        for order in (tx, tx[::-1]):
            r = run_audit(rows, order)
            assert not _satisfied(r)
            assert r["groups"][0]["missing"] == 1


# ── Honors fills ─────────────────────────────────────────────────────────────

def test_honors_fill_takes_the_passed_cross_listing():
    # ENGL 137H failed, CAS 137H (its cross-listing) passed -> ENGL 15 is met.
    rows = [_req("ENGL 15")]
    assert _both_orders(rows, _fail("ENGL 137"), _tx("CAS 137")) == (True, True)


def test_honors_fill_never_overrides_real_passing_row():
    # Real ENGL 15 with a C, RCL with an A: the real row stays the answer.
    rows = [_req("ENGL 15")]
    for order in ([_tx("ENGL 15", grade="C", credits=3), _tx("ENGL 137", credits=4)],
                  [_tx("ENGL 137", credits=4), _tx("ENGL 15", grade="C", credits=3)]):
        g = run_audit(rows, order)["groups"][0]
        assert g["satisfied"] and g["credits_earned"] == 3


def test_honors_fill_beats_failed_real_row():
    rows = [_req("ENGL 15")]
    assert _both_orders(rows, _fail("ENGL 15"), _tx("ENGL 137")) == (True, True)


# ── Pools: no double counting ────────────────────────────────────────────────

def test_pool_does_not_double_count_variant_and_exact():
    # Pool names both CAS 100 and CAS 100B; the student has one passed attempt
    # (100B) and a failed 100A. Only 3 credits exist, 6 are needed.
    rows = [_req("CAS 100", gtype="choose_credits", group_threshold=6),
            _req("CAS 100B", gtype="choose_credits", group_threshold=6),
            _req("CAS 100A", gtype="choose_credits", group_threshold=6)]
    for order in ([_fail("CAS 100A"), _tx("CAS 100B")], [_tx("CAS 100B"), _fail("CAS 100A")]):
        g = run_audit(rows, order)["groups"][0]
        assert not g["satisfied"]
        assert g["credits_earned"] == 3


def test_pool_does_not_double_count_cross_listing():
    rows = [_req("CMAS 258", gtype="choose_credits", group_threshold=6),
            _req("HDFS 258", gtype="choose_credits", group_threshold=6)]
    for order in ([_fail("CMAS 258"), _tx("HDFS 258")], [_tx("HDFS 258"), _fail("CMAS 258")]):
        g = run_audit(rows, order)["groups"][0]
        assert not g["satisfied"]
        assert g["credits_earned"] == 3


def test_exclusive_credential_does_not_reuse_one_attempt():
    rows = [_req("CAS 100", group="A"), _req("CAS 100B", group="B")]
    for order in ([_fail("CAS 100A"), _tx("CAS 100B")], [_tx("CAS 100B"), _fail("CAS 100A")]):
        r = run_audit(rows, order, exclusive=True)
        assert sum(g["satisfied"] for g in r["groups"]) == 1


def test_gen_ed_variant_order_independent():
    rows = [_req("CAS 100", group="Speech", gtype="choose_one", pair_group_id="1"),
            _req("ENGL 15", group="Speech", gtype="choose_one", pair_group_id="1")]
    a, b = _fail("CAS 100A"), _tx("CAS 100B")
    res = [run_gen_ed_audit(rows, order) for order in ([a, b], [b, a])]
    assert all(_satisfied(r, "Speech") for r in res)


# ── Writing Across the Curriculum ────────────────────────────────────────────

def test_wac_counts_transfer_credit():
    rows = [_req("", group="WAC", gtype="writing_intensive", group_threshold=3)]
    r = run_audit(rows, [_tx("HIST 20", status="transfer", grade="TR", is_writing=True)])
    g = r["groups"][0]
    assert g["satisfied"] and g["credits_earned"] == 3


def test_wac_still_ignores_failed():
    rows = [_req("", group="WAC", gtype="writing_intensive", group_threshold=3)]
    r = run_audit(rows, [_tx("HIST 20", status="failed", grade="F", credits=0, is_writing=True)])
    assert not r["groups"][0]["satisfied"]


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
           if n.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)} passed")
