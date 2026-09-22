"""
Tests for the requirement-pool split.

A CourseLeaf requirement section routinely holds SEVERAL independent pools, each
introduced by its own "Select N credits from the following:" row and each listing
its members inside a <div class="blockindent">.  The scraper used to notice only
the first, and the audit engine bucketed pools by (group_type, threshold) — so
every same-threshold pool in a section merged into one.

ETI's "Additional Courses" has four 3-credit pools (speech, writing, intro
programming, intro IST).  Merged, a single ENGL 15 satisfied all four, and
CYBER 100 / IST 140 / the speech requirement disappeared from the audit and the
timeline.  The app told students they owed LESS than they did, which is the
dangerous direction.

Runnable two ways:
  * pytest:        cd backend && python -m pytest tests/test_pool_split.py -v
  * plain python:  cd backend && python tests/test_pool_split.py

Hermetic — the scraper tests parse a saved fixture of the real ETI bulletin
table, no network and no DynamoDB.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from bs4 import BeautifulSoup

from audit_engine import run_audit
from routers.timeline import _collect_missing, _pool_slot_key

import scrape_psu

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


# ── Scraper harness ──────────────────────────────────────────────────────────
#
# scrape_program_requirements() fetches its own page, so the tests hand it a
# parsed fixture instead of hitting bulletins.psu.edu.

def _scrape_html(html: str, name: str = "Test Program, B.S."):
    original = scrape_psu.get_soup
    scrape_psu.get_soup = lambda url, retries=3: BeautifulSoup(html, "html.parser")
    try:
        rows, _summary = scrape_psu.scrape_program_requirements(
            {"url": "http://example.invalid/test/", "name": name, "college": "test-college"}
        )
    finally:
        scrape_psu.get_soup = original
    return rows


def _pools(rows):
    """{(group, threshold, pool_seq): {course codes}} for pool rows only."""
    out = {}
    for r in rows:
        if r.get("group_type") not in ("choose_credits", "choose_courses"):
            continue
        key = (r["requirement_group"], r.get("group_threshold"), r.get("pool_seq"))
        out.setdefault(key, set()).add(r["course_code"])
    return out


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


# ── 1. The real ETI table ────────────────────────────────────────────────────

def test_eti_fixture_yields_six_distinct_pools():
    """The bulletin lists six 'Select N credits' pools. We must store six."""
    rows = _scrape_html(_fixture("eti_courselist.html"))
    pools = _pools(rows)
    assert len(pools) == 6, f"expected 6 pools, got {len(pools)}: {sorted(pools)}"


def test_eti_pools_have_the_right_members():
    rows = _scrape_html(_fixture("eti_courselist.html"))
    by_members = {frozenset(v): k for k, v in _pools(rows).items()}

    expected = [
        # (members, threshold)
        ({"CAS 100A", "CAS 100B", "CAS 100C", "ENGL 138T"}, 3),
        ({"ENGL 137H", "ENGL 15", "ENGL 30H"}, 3),
        ({"BA 243", "BA 301", "BA 303", "BA 304", "BLAW 243",
          "FIN 301", "IB 303", "MGMT 301", "MKTG 301"}, 3),
        ({"CMPSC 121", "CMPSC 131", "IST 140"}, 3),
        ({"CMPSC 122", "CMPSC 132", "IST 242"}, 3),
        ({"A-I 100", "CYBER 100", "CYBER 100S", "ETI 100",
          "HCDD 113", "HCDD 113S", "IST 110"}, 3),
    ]
    for members, threshold in expected:
        key = by_members.get(frozenset(members))
        assert key is not None, f"pool missing or mis-split: {sorted(members)}"
        assert key[1] == threshold, f"{sorted(members)} threshold {key[1]} != {threshold}"


def test_eti_pool_seqs_are_distinct_and_contiguous():
    rows = _scrape_html(_fixture("eti_courselist.html"))
    seqs = sorted({k[2] for k in _pools(rows)})
    assert seqs == [1, 2, 3, 4, 5, 6], seqs


def test_cyber_100_and_ist_140_are_in_different_pools():
    """The regression that started this: both were swallowed by one 3-credit
    pool that ENGL 15 satisfied on its own."""
    rows = _scrape_html(_fixture("eti_courselist.html"))
    seq = {r["course_code"]: r.get("pool_seq") for r in rows if r.get("pool_seq")}
    assert seq["CYBER 100"] != seq["IST 140"]
    assert seq["CYBER 100"] != seq["ENGL 15"]
    assert seq["IST 140"] != seq["ENGL 15"]
    assert seq["CAS 100C"] != seq["ENGL 15"]


def test_prescribed_courses_are_not_pool_members():
    """Prescribed rows sit above the pools and are not indented. None of them
    may pick up a pool_seq or a pool group_type."""
    rows = _scrape_html(_fixture("eti_courselist.html"))
    by_code = {r["course_code"]: r for r in rows}
    for code in ("ETI 200", "ETI 300W", "IST 210", "IST 220", "IST 230", "IST 256"):
        assert by_code[code].get("pool_seq") is None, code
        assert by_code[code]["group_type"] != "choose_credits", code


# ── 2. Synthetic shapes ──────────────────────────────────────────────────────

_TBL_HEAD = ('<html><body><div id="requirementstab"><h2>Requirements for the Major</h2>'
             '<table class="sc_courselist">')
_TBL_FOOT = "</table></div></body></html>"


def _comment_row(text, credits=""):
    return (f'<tr class="odd"><td class="codecol" colspan="2"><span class="courselistcomment">'
            f'{text}</span></td><td class="hourscol">{credits}</td></tr>')


def _course_row(code, title, indent=True, credits=""):
    inner = f'<a class="bubblelink code">{code}</a>'
    if indent:
        inner = f'<div class="blockindent">{inner}</div>'
    return (f'<tr class="even"><td class="codecol">{inner}</td>'
            f'<td>{title}</td><td class="hourscol">{credits}</td></tr>')


def test_two_adjacent_same_threshold_pools_stay_separate():
    html = _TBL_HEAD + (
        _comment_row("Select 3 credits from the following:", "3")
        + _course_row("AAA 101", "One")
        + _course_row("AAA 102", "Two")
        + _comment_row("Select 3 credits from the following:", "3")
        + _course_row("BBB 201", "Three")
        + _course_row("BBB 202", "Four")
    ) + _TBL_FOOT
    pools = _pools(_scrape_html(html))
    assert len(pools) == 2, sorted(pools)
    assert {frozenset(v) for v in pools.values()} == {
        frozenset({"AAA 101", "AAA 102"}), frozenset({"BBB 201", "BBB 202"})
    }


def test_unindented_row_closes_the_pool():
    """A pool at the TOP of a table used to leak its type and threshold onto
    every prescribed course below it, quietly demoting required courses to pool
    options. An unindented row ends the pool."""
    html = _TBL_HEAD + (
        _comment_row("Select 3 credits from the following:", "3")
        + _course_row("AAA 101", "One")
        + _course_row("AAA 102", "Two")
        + _course_row("REQ 300", "Required", indent=False, credits="3")
        + _course_row("REQ 301", "Also required", indent=False, credits="3")
    ) + _TBL_FOOT
    rows = _scrape_html(html)
    by_code = {r["course_code"]: r for r in rows}
    assert by_code["AAA 101"]["group_type"] == "choose_credits"
    for code in ("REQ 300", "REQ 301"):
        assert by_code[code]["group_type"] == "required", by_code[code]
        assert by_code[code].get("pool_seq") is None
        assert by_code[code].get("group_threshold") is None


def test_comment_row_with_no_indented_list_is_not_a_pool():
    """Not every "Select N credits" row introduces a list. Aerospace
    Engineering's "Additional Courses" opens with "Select 1 credit of First-Year
    Seminar" — a standalone instruction — immediately followed by the ordinary
    requirement "AERSP 413 or AERSP 450". Treating the comment as a pool header
    swallowed both into a 1-credit First-Year Seminar pool."""
    html = _TBL_HEAD + (
        _comment_row("Select 1 credit of First-Year Seminar", "1")
        + _course_row("AAA 413", "Stability and Control", indent=False, credits="3")
        + _or_row("AAA 450", "Orbit and Attitude Control", indent=False)
    ) + _TBL_FOOT
    rows = _scrape_html(html)
    assert _pools(rows) == {}, "no pool should have been created"
    assert all(r["group_type"] == "choose_one" for r in rows),         [(r["course_code"], r["group_type"]) for r in rows]
    pids = {r.get("pair_group_id") for r in rows}
    assert len(pids) == 1 and None not in pids,         f"the either/or pair must survive intact: {pids}"


def test_discarded_comment_row_does_not_consume_a_pool_number():
    html = _TBL_HEAD + (
        _comment_row("Select 1 credit of First-Year Seminar", "1")
        + _course_row("AAA 413", "Standalone", indent=False, credits="3")
        + _comment_row("Select 3 credits from the following:", "3")
        + _course_row("BBB 201", "Pool option")
        + _course_row("BBB 202", "Pool option")
    ) + _TBL_FOOT
    pools = _pools(_scrape_html(html))
    assert len(pools) == 1
    assert next(iter(pools))[2] == 1, f"pool numbering should start at 1: {sorted(pools)}"


def test_indent_rule_only_closes_after_a_real_indented_member():
    """A pool that HAS indented members still closes on the first unindented
    row — the hardening above must not disable the rule where it applies."""
    html = _TBL_HEAD + (
        _comment_row("Select 3 credits from the following:", "3")
        + _course_row("AAA 101", "One")
        + _course_row("REQ 300", "Required", indent=False, credits="3")
    ) + _TBL_FOOT
    by_code = {r["course_code"]: r for r in _scrape_html(html)}
    assert by_code["AAA 101"]["group_type"] == "choose_credits"
    assert by_code["REQ 300"]["group_type"] == "required"


def _or_row(code, title, indent=True):
    inner = f'or <a class="bubblelink code">{code}</a>'
    if indent:
        inner = f'<div class="blockindent">{inner}</div>'
    return (f'<tr class="orclass even"><td class="codecol">{inner}</td>'
            f'<td>{title}</td><td class="hourscol"></td></tr>')


def test_or_chain_inside_a_pool_stays_in_the_pool():
    """An "or" chain inside a credit pool is a set of OPTIONS, not a standalone
    choice. Lifting it into choose_one told the student they must take one of
    them — three mandatory courses where the bulletin asked for one."""
    html = _TBL_HEAD + (
        _comment_row("Select 3-4 credits of the following:", "3-4")
        + _course_row("AAA 101", "One")
        + _or_row("AAA 102", "One, cross-listed")
        + _course_row("BBB 201", "Two")
        + _or_row("BBB 202", "Two, cross-listed")
    ) + _TBL_FOOT
    rows = _scrape_html(html)
    assert all(r["group_type"] == "choose_credits" for r in rows),         [(r["course_code"], r["group_type"]) for r in rows]
    assert all(r.get("pair_group_id") is None for r in rows),         "a pool option must not be re-typed into a mandatory choose_one pair"
    pools = _pools(rows)
    assert len(pools) == 1
    assert set(next(iter(pools.values()))) == {"AAA 101", "AAA 102", "BBB 201", "BBB 202"}


def test_lone_or_partner_in_a_pool_is_not_left_individually_required():
    """The Administration of Justice shape: "BA 241 & BA 242 or BA 243" opening a
    pool. BA 243 used to land as a choose_one row with no partner id, and a lone
    choose_one row evaluates as individually REQUIRED."""
    html = _TBL_HEAD + (
        _comment_row("Select 3-4 credits of the following:", "3-4")
        + _course_row("AAA 101", "Combo half one")
        + _or_row("AAA 103", "The alternative")
        + _course_row("BBB 201", "Another option")
    ) + _TBL_FOOT
    by_code = {r["course_code"]: r for r in _scrape_html(html)}
    assert by_code["AAA 103"]["group_type"] == "choose_credits"
    assert by_code["AAA 103"].get("pair_group_id") is None
    assert by_code["AAA 103"].get("pool_seq") == 1


def test_or_chain_outside_a_pool_is_still_a_choose_one_pair():
    """The fix must not touch ordinary either/or requirements, which is where the
    pair_group_id machinery earns its keep."""
    html = _TBL_HEAD + (
        _course_row("AAA 101", "One", indent=False, credits="3")
        + _or_row("AAA 102", "Or the other", indent=False)
    ) + _TBL_FOOT
    rows = _scrape_html(html)
    assert all(r["group_type"] == "choose_one" for r in rows),         [(r["course_code"], r["group_type"]) for r in rows]
    pids = {r.get("pair_group_id") for r in rows}
    assert len(pids) == 1 and None not in pids, pids


def test_pool_header_counting_options_instead_of_credits():
    """"Select one of the following sequences:" is a pool header too. It matched
    nothing, so its options silently joined the pool above it."""
    html = _TBL_HEAD + (
        _comment_row("Select 5-6 credits of the following:", "5-6")
        + _course_row("AAA 210", "Statics and Strength")
        + _comment_row("Select one of the following sequences:", "5")
        + _course_row("BBB 401A", "Design - Preliminary")
        + _course_row("BBB 402A", "Other design - Preliminary")
    ) + _TBL_FOOT
    pools = _pools(_scrape_html(html))
    assert len(pools) == 2, sorted(pools)
    assert {frozenset(v) for v in pools.values()} == {
        frozenset({"AAA 210"}), frozenset({"BBB 401A", "BBB 402A"})
    }


def test_option_counting_header_uses_its_credit_figure_when_it_has_one():
    """A "sequence" option is usually an "&" combo, and only a credit threshold
    stops half a sequence from satisfying the whole pool. So prefer the hours
    column over the option count."""
    html = _TBL_HEAD + (
        _comment_row("Select one of the following sequences:", "5")
        + _course_row("BBB 401A", "Design")
        + _course_row("BBB 402A", "Other design")
    ) + _TBL_FOOT
    rows = _scrape_html(html)
    assert all(r["group_type"] == "choose_credits" for r in rows)
    assert {r["group_threshold"] for r in rows} == {5}


def test_option_counting_header_without_credits_counts_courses():
    html = _TBL_HEAD + (
        _comment_row("Select two of the following:")
        + _course_row("BBB 401", "One")
        + _course_row("BBB 402", "Two")
        + _course_row("BBB 403", "Three")
    ) + _TBL_FOOT
    rows = _scrape_html(html)
    assert all(r["group_type"] == "choose_courses" for r in rows),         [(r["course_code"], r["group_type"]) for r in rows]
    assert {r["group_threshold"] for r in rows} == {2}


def test_pool_does_not_leak_into_the_next_table():
    """CourseLeaf splits one section across several tables with no heading
    between them. A pool opened in the first table used to stay open into the
    second and swallow its prescribed courses — World Languages Education had
    WLED 300, a Prescribed Course, reported as a pool option."""
    html = ('<html><body><div id="requirementstab"><h2>Requirements</h2>'
            '<table class="sc_courselist">'
            + _comment_row("Select 3 credits from the following:", "3")
            + _course_row("AAA 101", "Option") + _course_row("AAA 102", "Option")
            + '</table><table class="sc_courselist">'
            + _course_row("REQ 300", "Prescribed", indent=False, credits="3")
            + "</table></div></body></html>")
    by_code = {r["course_code"]: r for r in _scrape_html(html)}
    assert by_code["REQ 300"]["group_type"] == "required", by_code["REQ 300"]
    assert by_code["REQ 300"].get("pool_seq") is None


def test_pool_numbering_keeps_counting_across_tables():
    """Restarting the count per table would give two pools in the same section
    the same number — the collision pool_seq exists to prevent."""
    html = ('<html><body><div id="requirementstab"><h2>Requirements</h2>'
            '<table class="sc_courselist">'
            + _comment_row("Select 3 credits from the following:", "3")
            + _course_row("AAA 101", "Option") + _course_row("AAA 102", "Option")
            + '</table><table class="sc_courselist">'
            + _comment_row("Select 3 credits from the following:", "3")
            + _course_row("BBB 201", "Option") + _course_row("BBB 202", "Option")
            + "</table></div></body></html>")
    pools = _pools(_scrape_html(html))
    assert len(pools) == 2, sorted(pools)
    assert sorted(k[2] for k in pools) == [1, 2]


def test_areaheader_row_closes_the_pool():
    """"Prescribed Courses" / "Additional Courses" are <tr class="areaheader">,
    not heading tags, so they never reset anything and a pool ran through."""
    html = _TBL_HEAD + (
        _comment_row("Select 3 credits from the following:", "3")
        + _course_row("AAA 101", "Option")
        + '<tr class="odd areaheader"><td colspan="3">Prescribed Courses</td></tr>'
        + _course_row("REQ 300", "Prescribed", indent=False, credits="3")
    ) + _TBL_FOOT
    by_code = {r["course_code"]: r for r in _scrape_html(html)}
    assert by_code["REQ 300"]["group_type"] == "required", by_code["REQ 300"]
    assert by_code["REQ 300"].get("pool_seq") is None


def test_pool_header_with_filler_words_before_credits():
    """Spanish B.A. heads two pools "Select 9 additional credits from the
    following". The word "additional" broke the match, so 34 courses fell through
    to the section default and were stored as individually REQUIRED — a Spanish
    major told to take every 200-, 300- and 400-level SPAN course on the page."""
    html = _TBL_HEAD + (
        _comment_row("Select 9 additional credits from the following 400-level list:", "9")
        + _course_row("AAA 410", "One")
        + _course_row("AAA 411", "Two")
    ) + _TBL_FOOT
    rows = _scrape_html(html)
    assert all(r["group_type"] == "choose_credits" for r in rows),         [(r["course_code"], r["group_type"]) for r in rows]
    assert {r["group_threshold"] for r in rows} == {9}


def test_areaheader_reset_does_not_strand_a_later_pool():
    """The areaheader reset and the filler-word gap interact: the reset removed
    the accidental type-leak that used to carry these rows, so a header the regex
    could not read left them required."""
    html = _TBL_HEAD + (
        _comment_row("Select 3 credits from the following:", "3")
        + _course_row("AAA 101", "Option")
        + '<tr class="even areaheader"><td colspan="3">Supporting Courses</td></tr>'
        + _comment_row("Select 9 additional credits from the following:", "9")
        + _course_row("BBB 210", "Option")
        + _course_row("BBB 220", "Option")
    ) + _TBL_FOOT
    pools = _pools(_scrape_html(html))
    assert len(pools) == 2, sorted(pools)
    assert sorted(k[1] for k in pools) == [3, 9]


def test_pool_seq_resets_on_a_new_section():
    html = ('<html><body><div id="requirementstab">'
            '<h2>Section One</h2><table class="sc_courselist">'
            + _comment_row("Select 3 credits from the following:", "3")
            + _course_row("AAA 101", "One") + _course_row("AAA 102", "Two")
            + '</table><h2>Section Two</h2><table class="sc_courselist">'
            + _comment_row("Select 3 credits from the following:", "3")
            + _course_row("BBB 201", "Three") + _course_row("BBB 202", "Four")
            + "</table></div></body></html>")
    pools = _pools(_scrape_html(html))
    assert len(pools) == 2
    assert {k[2] for k in pools} == {1}, "each section numbers its pools from 1"
    assert {k[0] for k in pools} == {"Section One", "Section Two"}


def test_pool_introduced_by_a_paragraph_before_the_table():
    """Some pages put the instruction outside the table, so the members carry no
    blockindent. That pool must still open, and must not be closed by its own
    unindented members."""
    html = ('<html><body><div id="requirementstab"><h2>Supporting Courses</h2>'
            '<p>Select 6 credits from the following:</p>'
            '<table class="sc_courselist">'
            + _course_row("AAA 101", "One", indent=False)
            + _course_row("AAA 102", "Two", indent=False)
            + "</table></div></body></html>")
    pools = _pools(_scrape_html(html))
    assert len(pools) == 1, sorted(pools)
    (key, members), = pools.items()
    assert members == {"AAA 101", "AAA 102"}
    assert key[1] == 6


# ── 3. Audit engine ──────────────────────────────────────────────────────────

def _req(code, group="Additional Courses", gtype="choose_credits",
         threshold=3, pool_seq=None, credits=3):
    row = {"program_name": "X", "requirement_group": group, "group_type": gtype,
           "course_code": code, "credits": credits, "group_threshold": threshold}
    if pool_seq is not None:
        row["pool_seq"] = pool_seq
    return row


def _tx(code, status="done", grade="A", credits=3):
    return {"course_code": code, "status": status, "grade": grade,
            "credits_earned": credits, "credits": credits}


def _subgroups(result):
    """Every evaluated pool/group. A homogeneous section has no `sub_groups` and
    reports its type as `group_type`; a mixed one splits into `sub_groups` that
    report `sub_type`. Reading only one of the two silently sees no pools."""
    for g in result["groups"]:
        for src in (g.get("sub_groups") or [g]):
            yield src


def _ptype(src):
    return src.get("sub_type") or src.get("group_type")


def _pools_of(result, kind="choose_credits"):
    return [s for s in _subgroups(result) if _ptype(s) == kind]


def _pool_for(result, code):
    for src in _subgroups(result):
        if any(i["course_code"] == code for i in src.get("items", [])):
            return src
    return None


ETI_LIKE_ROWS = (
    [_req(c, pool_seq=1) for c in ("CAS 100A", "CAS 100B", "CAS 100C")]
    + [_req(c, pool_seq=2) for c in ("ENGL 137H", "ENGL 15", "ENGL 30H")]
    + [_req(c, pool_seq=3) for c in ("CMPSC 121", "CMPSC 131", "IST 140")]
    + [_req(c, pool_seq=4) for c in ("CYBER 100", "ETI 100", "IST 110")]
)


def test_same_threshold_pools_evaluate_separately():
    res = run_audit(copy.deepcopy(ETI_LIKE_ROWS), [_tx("ENGL 15")])
    pools = _pools_of(res)
    assert len(pools) == 4, f"expected 4 pools, got {len(pools)}"
    assert _pool_for(res, "ENGL 15")["satisfied"] is True
    for code in ("CAS 100A", "IST 140", "CYBER 100"):
        assert _pool_for(res, code)["satisfied"] is False, code


def test_one_course_no_longer_satisfies_four_pools():
    """The exact bug: with the pools merged, ENGL 15 alone closed out 12 credits
    of distinct requirements."""
    merged = [dict(r) for r in ETI_LIKE_ROWS]
    for r in merged:
        r.pop("pool_seq", None)
    merged_res = run_audit(merged, [_tx("ENGL 15")])
    split_res = run_audit(copy.deepcopy(ETI_LIKE_ROWS), [_tx("ENGL 15")])

    merged_pools = _pools_of(merged_res)
    assert len(merged_pools) == 1 and merged_pools[0]["satisfied"] is True, \
        "characterizes the old behaviour"
    assert not all(s["satisfied"] for s in _pools_of(split_res))


def test_each_pool_is_satisfied_by_its_own_member():
    res = run_audit(copy.deepcopy(ETI_LIKE_ROWS),
                    [_tx("CAS 100C"), _tx("ENGL 15"), _tx("IST 140"), _tx("CYBER 100")])
    pools = _pools_of(res)
    assert len(pools) == 4
    assert all(s["satisfied"] for s in pools)


def test_in_progress_course_counts_toward_its_own_pool_only():
    """`satisfied` on a choose_credits pool counts COMPLETED credits only — the
    timeline is what folds in-progress work in (`_collect_missing`). So this is
    asserted where the student actually sees it: an in-progress CMPSC 131 must
    take the programming pool off the plan and leave the other three on it."""
    res = run_audit(copy.deepcopy(ETI_LIKE_ROWS),
                    [_tx("CMPSC 131", status="in_progress", grade="")])
    offered = [{o["course_code"] for o in m["options"]}
               for m in _collect_missing(res) if m.get("is_pool")]
    assert len(offered) == 3, offered
    assert not any("IST 140" in o for o in offered), "programming pool still scheduled"
    assert any("CYBER 100" in o for o in offered), "intro IST pool wrongly retired"


def test_rows_without_pool_seq_are_a_no_op():
    """Until the catalog is reloaded every row has no pool_seq. The engine must
    behave byte-identically for them, so it can ship ahead of the data."""
    rows = [_req(c, pool_seq=None) for c in ("AAA 1", "AAA 2", "BBB 1", "BBB 2")]
    res = run_audit(copy.deepcopy(rows), [_tx("AAA 1")])
    pools = _pools_of(res)
    assert len(pools) == 1
    assert pools[0]["satisfied"] is True


def test_pool_seq_zero_is_treated_as_absent():
    """The scraper writes 0 for 'not in a pool'; it must not create a bucket of
    its own distinct from None."""
    rows = ([_req("AAA 1", pool_seq=0), _req("AAA 2", pool_seq=None)])
    res = run_audit(copy.deepcopy(rows), [])
    pools = _pools_of(res)
    assert len(pools) == 1, [p.get("pool_seq") for p in pools]


def test_different_thresholds_still_split_without_pool_seq():
    """The pre-existing (type, threshold) split must keep working."""
    rows = [_req("AAA 1", threshold=3), _req("BBB 1", threshold=9)]
    res = run_audit(rows, [])
    pools = sorted(_pools_of(res), key=lambda s: s["threshold"])
    assert [s["threshold"] for s in pools] == [3, 9]


def test_required_rows_are_unaffected_by_pool_seq():
    rows = [_req("AAA 1", gtype="required", threshold=None),
            _req("BBB 1", gtype="required", threshold=None)]
    res = run_audit(rows, [_tx("AAA 1")])
    assert res["done"] == 1 and res["missing"] == 1


# ── 4. Timeline slot keys ────────────────────────────────────────────────────

def test_pool_slot_key_is_unchanged_for_the_first_pool():
    """Choices already stored under the bare key must not be orphaned."""
    legacy = _pool_slot_key("Supporting Courses")
    assert legacy == "pool:SUPPORTING_COURSES"
    assert _pool_slot_key("Supporting Courses", None) == legacy
    assert _pool_slot_key("Supporting Courses", 0) == legacy
    assert _pool_slot_key("Supporting Courses", 1) == legacy


def test_pool_slot_key_disambiguates_later_pools():
    keys = {_pool_slot_key("Additional Courses", i) for i in (1, 2, 3, 4)}
    assert len(keys) == 4, keys
    assert "pool:ADDITIONAL_COURSES" in keys
    assert "pool:ADDITIONAL_COURSES@4" in keys


def test_disambiguated_slot_key_is_still_storable():
    """The suffix must survive `PUT /user-choices` validation — it rejects "/"
    and the reserved `sub:` / `cred:` namespaces."""
    from routers.user_choices import _RESERVED_PREFIXES

    key = _pool_slot_key("Additional Courses", 4)
    assert "/" not in key
    assert not key.startswith(_RESERVED_PREFIXES)
    # and after _expand_pool appends its per-slice suffix
    assert "/" not in f"{key}#2"


def test_timeline_emits_one_slot_per_unsatisfied_pool():
    res = run_audit(copy.deepcopy(ETI_LIKE_ROWS), [_tx("ENGL 15")])
    missing = _collect_missing(res)
    pool_slots = [m for m in missing if m.get("is_pool")]
    assert len(pool_slots) == 3, [m.get("slot_key") for m in pool_slots]
    assert len({m["slot_key"] for m in pool_slots}) == 3, "slot keys must not collide"


def test_timeline_pool_slots_offer_their_own_courses():
    res = run_audit(copy.deepcopy(ETI_LIKE_ROWS), [_tx("ENGL 15")])
    by_key = {m["slot_key"]: {o["course_code"] for o in m["options"]}
              for m in _collect_missing(res) if m.get("is_pool")}
    offered = list(by_key.values())
    assert {"CYBER 100", "ETI 100", "IST 110"} in offered
    assert {"CMPSC 121", "CMPSC 131", "IST 140"} in offered
    # No pool may offer a course belonging to another pool.
    for a in offered:
        for b in offered:
            if a is not b:
                assert not (a & b), f"pools overlap: {a & b}"


def test_satisfied_pool_emits_nothing():
    res = run_audit(copy.deepcopy(ETI_LIKE_ROWS),
                    [_tx("CAS 100C"), _tx("ENGL 15"), _tx("IST 140"), _tx("CYBER 100")])
    assert [m for m in _collect_missing(res) if m.get("is_pool")] == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
